# -*- coding: utf-8 -*-
"""A new workspace is fresh: made-up examples, nothing of Eko's (No. 247).

"For a new workspace use synthetic data, not the Eko data, as example — it
should be fresh, no hint of another workspace." Eko's own workspace is
unchanged.
"""

import io
import re
import uuid
import zipfile

import pytest
from docx import Document
from sqlalchemy import select, text

from app.services import (assistant_tools, document_registry, jwt_service,
                          lho_signature, org_identity, quality_texts,
                          workspace_service, workspace_settings)
from app.services import signature_rules as sr
from app.services.workspace_settings import EKO_WORKSPACE
from app.workspace_context import all_workspaces, workspace

OWNER = "fresh.owner@eko.co.in"
EKO_WORDS = re.compile(r"eko|ganesh|state bank|\bsbi\b|9217060639|9821946420|1a85", re.I)


def _eko_in_docx(data: bytes) -> list:
    found = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith((".xml", ".rels")):
                body = re.sub(r"<[^>]+>", " ", z.read(name).decode("utf-8", "replace"))
                found += [f"{name}: {m.group(0)}" for m in EKO_WORDS.finditer(body)]
                targets = " ".join(re.findall(r'Target="([^"]+)"', z.read(name).decode("utf-8", "replace")))
                found += [f"{name} link: {m.group(0)}" for m in EKO_WORDS.finditer(targets)]
    return found


# ---- no database --------------------------------------------------------------------

def test_the_sample_designs_carry_nothing_of_ekos():
    rows = workspace_service.sample_documents(uuid.uuid4())
    assert len(rows) == 4
    with open(lho_signature.default_path(), "rb") as f:
        eko_sign = f.read()
    for row in rows:
        assert not _eko_in_docx(row.file_data), (row.code, _eko_in_docx(row.file_data))
        blobs = [b["blob"] for b in sr.pictures_in(Document(io.BytesIO(row.file_data))).values()]
        assert eko_sign not in blobs, row.code
        # The sample signature is in the file, and is where a rule's goes.
        assert row.signature_spot and row.signature_spot[8:] in {sr.sha256(b) for b in blobs}
        assert row.active is False and row.is_builtin is True


def test_eko_messages_are_unchanged_and_another_workspace_uses_its_own_name(monkeypatch):
    with workspace(EKO_WORKSPACE):
        assert org_identity.swap(assistant_tools.WHATSAPP_WORDING) == assistant_tools.WHATSAPP_WORDING
        assert org_identity.organisation_name() == "Eko Bharat Ventures Pvt Ltd"
        help_text = "The tab with one row per record (Eko: KOData)."
        assert org_identity.neutral(help_text) == help_text
    from app.services import workspace_files
    monkeypatch.setattr(workspace_files, "workspace_name", lambda: "Sunrise Services")
    with workspace(uuid.uuid4()):
        wording = org_identity.swap(assistant_tools.WHATSAPP_WORDING)
        assert "Sunrise Services" in wording and "Eko" not in wording
        from app.services import documents_whatsapp, documents_feedback, email_service
        for body in (documents_whatsapp.BODY, documents_feedback.WORDING):
            assert "Eko" not in org_identity.swap(body)
        assert "Team Sunrise Services" in org_identity.swap(documents_whatsapp.BODY)
        assert email_service.documents_subject("X1").endswith("| Sunrise Services")
        html = email_service._build_documents_html("A", "X1", ["ID Card"], with_logo=False)
        assert "Eko" not in html and "Sunrise Services" in html
        assert "Eko" not in email_service._build_documents_plain("A", "X1", ["ID Card"])
        assert email_service._logo_part() is None
        assert org_identity.neutral("The tab with one row per record (Eko: KOData).") == \
            "The tab with one row per record."


def test_ekos_folder_signatures_never_reach_another_workspace(monkeypatch):
    if not lho_signature.own_signature_path("Patna"):
        pytest.skip("no Patna picture in this checkout")
    with workspace(uuid.uuid4()):
        assert lho_signature.apply(object(), "Patna") is None


def test_ekos_own_rules_are_not_another_workspaces_starting_rules():
    class W:
        id = uuid.uuid4()
        settings = {}
    titles = {g["title"] for g in quality_texts.guardrails(W())}
    assert not titles & quality_texts.EKO_ONLY_GUARDRAILS

    class E:
        id = EKO_WORKSPACE
        settings = {}
    assert quality_texts.EKO_ONLY_GUARDRAILS <= {g["title"] for g in quality_texts.guardrails(E())}


# ---- database --------------------------------------------------------------------------

async def _new(starter):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        ws = await workspace_service.create_workspace(
            s, f"Fresh Test {uuid.uuid4().hex[:6]}", OWNER, "Owner", starter=starter)
        await s.commit()
        return ws


async def _drop(ws):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with all_workspaces():
            await s.execute(text("DELETE FROM signatures WHERE workspace_id = :w").bindparams(w=ws.id))
            await s.execute(text("DELETE FROM workspaces WHERE id = :w").bindparams(w=ws.id))
            await s.commit()
    workspace_settings.forget()
    document_registry.invalidate()


def _h(ws):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": OWNER, "email": OWNER, "role": "super_admin", "name": "O", "ws": str(ws.id)})}


@pytest.mark.asyncio(loop_scope="session")
async def test_ready_made_start_has_samples_and_a_blank_one_has_nothing_of_ekos(client, migrated_db):
    from app.database import async_session_factory
    from app.models.document_template import DocumentTemplate
    from app.models.signature import Signature
    ready, blank = await _new("eko"), await _new("blank")
    try:
        async with async_session_factory() as s:
            with workspace(ready.id):
                docs = (await s.execute(select(DocumentTemplate))).scalars().all()
                assert len(docs) == 4
                for d in docs:
                    assert d.file_data and not _eko_in_docx(bytes(d.file_data)), d.code
                sigs = (await s.execute(select(Signature))).scalars().all()
                assert [x.name for x in sigs] == ["Sample signature"]
        document_registry.invalidate()
        with workspace(blank.id):
            assert document_registry._load() == {}
        with workspace(ready.id):
            assert set(document_registry._load()) == {d.code for d in docs}

        # The ready-made documents are made for a made-up CSP, with the
        # sample signature, and say nothing of Eko.
        for d in docs:
            r = await client.post(f"/api/admin/templates/{d.code}/test", headers=_h(ready),
                                  json={"csp_id": "SAMPLE"})
            assert r.status_code == 200, r.text
            assert "Asha Verma" in "\n".join(p.text for p in Document(io.BytesIO(r.content)).paragraphs) \
                or d.code != "CSP_CERTIFICATE"
            assert not _eko_in_docx(r.content), (d.code, _eko_in_docx(r.content))

        # The settings screen's help says nothing of Eko for this workspace.
        r = await client.get("/api/admin/settings", headers=_h(ready))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["settings"]
        for item in body["settings"]:
            assert "Eko" not in (item.get("help") or ""), item["key"]
            assert "Eko" not in (item.get("effect") or ""), item["key"]
        assert "Eko" not in body.get("note", "")
        r = await client.get("/api/me/access", headers=_h(ready))
        assert r.status_code == 200
        look = r.json()["look"]
        assert look["sender_org"] == ready.name and "Eko" not in look["sender_short"]
    finally:
        await _drop(ready)
        await _drop(blank)
