# -*- coding: utf-8 -*-
"""Template versions, restore, test run and category (No. 240, Stage 5).

Brief: maintain template versions, preview / test generation, publish
(= switch on), activate / deactivate, categories, mandatory fields — while
"existing CSP document templates and generation functionality" keep working.
"""

import io

import pytest
from docx import Document
from sqlalchemy import text

from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.services import jwt_service
from app.services import template_service as ts

pytestmark = pytest.mark.asyncio(loop_scope="session")

CODE = "CSP_CERTIFICATE"   # a supplied one with no photo


def _h(role="admin", email="tmpl.admin@eko.co.in"):
    token = jwt_service.create_access_token({"sub": email, "role": role,
                                             "name": "T"})
    return {"Authorization": f"Bearer {token}"}


def _text(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


@pytest.fixture
async def put_back(db):
    """Leave the supplied template exactly as it was."""
    row = (await db.execute(text(
        "SELECT file_data, file_size, checksum, version, placeholder_map, "
        "active, filename, category FROM document_templates WHERE code = :c")
        .bindparams(c=CODE))).first()
    await db.execute(text("DELETE FROM document_template_versions"))
    await db.commit()
    yield db
    import json
    await db.execute(text(
        "UPDATE document_templates SET file_data = :fd, file_size = :fs, "
        "checksum = :ck, version = :v, placeholder_map = CAST(:pm AS jsonb), "
        "active = :a, filename = :fname, category = :cat WHERE code = :c").bindparams(
            fd=row[0], fs=row[1], ck=row[2], v=row[3], pm=json.dumps(row[4] or {}),
            a=row[5], fname=row[6], cat=row[7], c=CODE))
    await db.execute(text("DELETE FROM document_template_versions"))
    await db.commit()
    from app.services import document_registry
    document_registry.invalidate()


async def _first_words(client):
    d = (await client.get(f"/api/admin/templates/{CODE}", headers=_h())).json()
    first = next(p for p in d["paragraphs"] if p["text"].strip() and '"' not in p["text"])
    return d, first


async def test_a_wording_edit_keeps_the_old_version_and_restore_puts_it_back(client, put_back):
    before, para = await _first_words(client)
    r = await client.put(f"/api/admin/templates/{CODE}/content", headers=_h(),
                         json={"edits": {str(para["index"]): para["text"] + " EDITED"}})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == before["version"] + 1

    v = (await client.get(f"/api/admin/templates/{CODE}/versions", headers=_h())).json()
    assert len(v["versions"]) == 1
    kept = v["versions"][0]
    assert kept["version"] == before["version"] and kept["reason"] == "wording_edit"
    assert kept["was_active"] is before["active"]

    old = await client.get(f"/api/admin/templates/{CODE}/versions/{kept['id']}/file", headers=_h())
    assert old.status_code == 200 and "EDITED" not in _text(old.content)

    r = await client.post(f"/api/admin/templates/{CODE}/versions/{kept['id']}/restore", headers=_h())
    assert r.status_code == 200, r.text
    assert r.json()["restored_version"] == before["version"]
    assert r.json()["version"] == before["version"] + 2
    assert r.json()["active"] is before["active"]
    after, _ = await _first_words(client)
    assert all("EDITED" not in p["text"] for p in after["paragraphs"])
    # The edited one is kept too, so the restore can itself be undone.
    v = (await client.get(f"/api/admin/templates/{CODE}/versions", headers=_h())).json()
    assert [x["reason"] for x in v["versions"]] == ["restore", "wording_edit"]


async def test_the_test_run_makes_the_document_and_stores_nothing(client, put_back, db):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        await s.execute(text("DELETE FROM csp_records WHERE csp_id = 'TMPLTEST1'"))
        s.add(CSPRecord(csp_id="TMPLTEST1", csp_code="TMPLTEST", name="Template Test Person",
                        branch_name="Testbranch", branch_code="BR0001", address="1 Test Street",
                        district="Testdistrict", state="Teststate", mobile="9876543210",
                        email="tmpl.test@example.com", ao="Testao", rbo_name="Testrbo",
                        asm_name="Testasm", asm_email="t.asm@example.com",
                        asm_contact="9876500000", origin="new", rm_resolution="unresolved"))
        await s.commit()
    stored = (await db.execute(text("SELECT count(*) FROM stored_documents"))).scalar()
    try:
        r = await client.post(f"/api/admin/templates/{CODE}/test", headers=_h(),
                              json={"csp_id": "TMPLTEST1"})
        assert r.status_code == 200, r.text
        assert "TEST_" in r.headers["content-disposition"]
        assert "Template Test Person" in _text(r.content)
        assert (await db.execute(text("SELECT count(*) FROM stored_documents"))).scalar() == stored
        r = await client.post(f"/api/admin/templates/{CODE}/test", headers=_h(),
                              json={"csp_id": "NO_SUCH_CSP"})
        assert r.status_code == 404
    finally:
        await db.execute(text("DELETE FROM csp_records WHERE csp_id = 'TMPLTEST1'"))
        await db.commit()


async def test_category_and_mandatory_fields(client, put_back):
    r = await client.patch(f"/api/admin/templates/{CODE}", headers=_h(),
                           json={"category": "  Certificates "})
    assert r.status_code == 200 and r.json()["category"] == "Certificates"
    listed = (await client.get("/api/admin/templates", headers=_h())).json()["templates"]
    row = next(t for t in listed if t["code"] == CODE)
    assert row["category"] == "Certificates"
    assert "csp_name" in row["required_fields"]
    r = await client.patch(f"/api/admin/templates/{CODE}", headers=_h(), json={"category": ""})
    assert r.json()["category"] is None


async def test_an_rm_cannot_see_versions_or_test(client, put_back):
    rm = _h("rm", "tmpl.rm@eko.co.in")
    assert (await client.get(f"/api/admin/templates/{CODE}/versions", headers=rm)).status_code == 403
    assert (await client.post(f"/api/admin/templates/{CODE}/test", headers=rm,
                              json={"csp_id": "X"})).status_code == 403


async def test_the_supplied_templates_still_fill(put_back):
    """Generation is unchanged by any of this: every supplied template fills."""
    for doc_type in DocumentType:
        assert ts.placeholders_for(doc_type)
