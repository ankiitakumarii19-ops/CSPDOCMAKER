# -*- coding: utf-8 -*-
"""Signatures chosen by rule (No. 247).

"Add options where we can add a document and a signature applied on them —
the user can select this sign on this document for these values of this
column." With no rule, every document is made exactly as before.
"""

import io
import os

import pytest
from docx import Document
from PIL import Image
from sqlalchemy import text

from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.services import jwt_service, lho_signature
from app.services import signature_rules as sr
from app.services import template_service as ts

CODE = "CSP_CERTIFICATE"   # a supplied one with no photo


def _png(colour="navy", size=(300, 100)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


def _rule(name="Sign A", column="lho", values=("Patna",), code=None, image=None, **kw):
    png, w, h = sr.check_picture(image or _png())
    return sr.Rule(id=name, document_code=code, column=column, values=list(values),
                   signature_id=name, signature_name=name, image=png, width=w,
                   height=h, **kw)


def _blobs(path_or_bytes) -> set:
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes
    return set(sr.pictures_in(Document(src)))


# ---- choosing the rule (no database) ------------------------------------------

def test_the_first_matching_rule_wins_and_values_ignore_case_and_spaces():
    rules = [_rule("Patna sign", values=(" PATNA ",)),
             _rule("Bihar sign", column="state", values=("Bihar",)),
             _rule("Everyone", column="", values=())]
    assert sr.first_match(rules, CODE, {"lho": "patna", "state": "Bihar"}).signature_name == "Patna sign"
    assert sr.first_match(rules, CODE, {"lho": "Lucknow", "state": "bihar"}).signature_name == "Bihar sign"
    assert sr.first_match(rules, CODE, {"lho": "Lucknow", "state": "UP"}).signature_name == "Everyone"


def test_a_rule_for_one_document_leaves_the_others_alone_and_off_rules_are_skipped():
    rules = [_rule("Only BCP", code="BCP"), _rule("Off", active=False)]
    assert sr.first_match(rules, "BCP", {"lho": "Patna"}).signature_name == "Only BCP"
    assert sr.first_match(rules, CODE, {"lho": "Patna"}) is None


def test_only_pictures_are_taken():
    with pytest.raises(sr.SignatureError):
        sr.check_picture(b"<svg onload='x'></svg>")
    with pytest.raises(sr.SignatureError):
        sr.check_picture(b"")
    png, w, h = sr.check_picture(_png(size=(3000, 1000)))
    assert (w, h) == (1500, 500) and png.startswith(b"\x89PNG")


def test_the_rule_in_words():
    assert sr.describe(_rule("Patna sign", values=("Patna", "Ranchi")), {}) == \
        "Every document, LHO is Patna or Ranchi → Patna sign"
    assert sr.describe(_rule("X", column="", code="BCP"), {"BCP": "BCP Letter"}) == \
        "BCP Letter, every other CSP → X"


# ---- putting it in the document (no database) ------------------------------------

def _values(doc_type):
    return {field: "Test value" for field in ts.placeholders_for(doc_type).values()} | {
        "csp_name": "Sign Test Person", "gender": "", "csp_code": "12345678"}


def test_no_record_or_no_rule_makes_the_document_exactly_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "rules", lambda: [_rule(values=("Somewhere else",))])
    default_sha = sr.default_spot()[len("picture:"):]
    for record in (None, {"lho": "Lucknow"}):
        out = ts.fill_template(DocumentType.CSP_CERTIFICATE, _values(DocumentType.CSP_CERTIFICATE),
                               str(tmp_path / "a.docx"), lho="Lucknow", record=record)
        assert default_sha in _blobs(out)


def test_a_matching_rule_replaces_the_supplied_signature(tmp_path, monkeypatch):
    rule = _rule("Patna sign")
    monkeypatch.setattr(sr, "rules", lambda: [rule])
    out = ts.fill_template(DocumentType.CSP_CERTIFICATE, _values(DocumentType.CSP_CERTIFICATE),
                           str(tmp_path / "b.docx"), lho="Patna", record={"lho": "Patna"})
    found = _blobs(out)
    assert sr.sha256(rule.image) in found
    assert sr.default_spot()[len("picture:"):] not in found
    # Patna's own folder picture is not put in on top of the rule's.
    own = lho_signature.own_signature_path("Patna")
    if own:
        with open(own, "rb") as f:
            assert sr.sha256(f.read()) not in found


def test_a_text_place_becomes_the_signature_and_an_uncovered_csp_is_refused(tmp_path, monkeypatch):
    doc = Document(ts.template_source(DocumentType.CSP_CERTIFICATE))
    line = next(p.text for p in doc.paragraphs
                if p.text.strip() and not ts._PLACEHOLDER_RE.search(p.text) and len(p.text) < 100)
    monkeypatch.setattr(sr, "spot_for", lambda code: "text:" + ts._squash(line))
    rule = _rule("Line sign")
    monkeypatch.setattr(sr, "rules", lambda: [rule])
    out = ts.fill_template(DocumentType.CSP_CERTIFICATE, _values(DocumentType.CSP_CERTIFICATE),
                           str(tmp_path / "c.docx"), record={"lho": "Patna"})
    filled = Document(out)
    assert sr.sha256(rule.image) in sr.pictures_in(filled)
    assert all(ts._squash(p.text) != ts._squash(line) for p in filled.paragraphs)
    with pytest.raises(ts.TemplateError, match="every other CSP"):
        ts.fill_template(DocumentType.CSP_CERTIFICATE, _values(DocumentType.CSP_CERTIFICATE),
                         str(tmp_path / "d.docx"), record={"lho": "Lucknow"})


def test_a_chosen_picture_missing_from_the_file_is_refused_not_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "spot_for", lambda code: "picture:" + "0" * 64)
    monkeypatch.setattr(sr, "rules", lambda: [_rule()])
    with pytest.raises(ts.TemplateError, match="not in its current file"):
        ts.fill_template(DocumentType.CSP_CERTIFICATE, _values(DocumentType.CSP_CERTIFICATE),
                         str(tmp_path / "e.docx"), record={"lho": "Patna"})


# ---- the screen's server side (database) --------------------------------------------

def _h(role="admin", email="sig.admin@eko.co.in"):
    token = jwt_service.create_access_token({"sub": email, "role": role, "name": "T"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def clean(db):
    async def wipe():
        await db.execute(text("DELETE FROM signature_rules"))
        await db.execute(text("DELETE FROM signatures"))
        await db.execute(text("UPDATE document_templates SET signature_spot = NULL"))
        await db.execute(text("DELETE FROM csp_records WHERE csp_id LIKE 'SIGTEST%'"))
        await db.commit()
        sr.forget()
        from app.services import document_registry
        document_registry.invalidate()
    await wipe()
    yield db
    await wipe()


async def _upload(client, name, colour="navy"):
    r = await client.post("/api/admin/signatures", headers=_h(),
                          data={"name": name}, files={"file": ("s.png", _png(colour), "image/png")})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio(loop_scope="session")
async def test_upload_rules_values_which_and_the_real_document(client, clean):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        s.add(CSPRecord(csp_id="SIGTEST1", csp_code="SIGTEST", name="Signature Test Person",
                        branch_name="Testbranch", branch_code="BR0001", address="1 Test Street",
                        district="Testdistrict", state="Teststate", mobile="9876543210",
                        email="sig.test@example.com", ao="Testao", rbo_name="Testrbo",
                        lho=" SIGLHO ", asm_name="Testasm", asm_email="t.asm@example.com",
                        asm_contact="9876500000", origin="new", rm_resolution="unresolved"))
        await s.commit()

    a = await _upload(client, "Sign A", "navy")
    b = await _upload(client, "Sign B", "maroon")
    dup = await client.post("/api/admin/signatures", headers=_h(), data={"name": "sign a"},
                            files={"file": ("s.png", _png(), "image/png")})
    assert dup.status_code == 409
    bad = await client.post("/api/admin/signatures", headers=_h(), data={"name": "Bad"},
                            files={"file": ("s.svg", b"<svg/>", "image/svg+xml")})
    assert bad.status_code == 400

    # The catch-all first, then a particular one: the particular one is put
    # before it, so it is reachable.
    r = await client.post("/api/admin/signatures/rules", headers=_h(),
                          json={"column": "", "signature_id": b["id"]})
    assert r.status_code == 201, r.text
    r = await client.post("/api/admin/signatures/rules", headers=_h(),
                          json={"document_code": CODE, "column": "lho",
                                "values": ["Siglho", "siglho "], "signature_id": a["id"]})
    assert r.status_code == 201, r.text
    over = (await client.get("/api/admin/signatures", headers=_h())).json()
    assert [x["signature_name"] for x in over["rules"]] == ["Sign A", "Sign B"]
    assert over["rules"][0]["values"] == ["Siglho"]
    assert {"key": "lho", "label": "LHO"} in over["columns"]

    vals = (await client.get("/api/admin/signatures/values?column=lho", headers=_h())).json()
    assert any(v["value"] == "SIGLHO" for v in vals["values"])
    assert (await client.get("/api/admin/signatures/values?column=password",
                             headers=_h())).status_code == 400

    which = (await client.get(f"/api/admin/signatures/which?code={CODE}&csp_id=SIGTEST1",
                              headers=_h())).json()
    assert which["signature"] == "Sign A"
    which = (await client.get("/api/admin/signatures/which?code=BCP&csp_id=SIGTEST1",
                              headers=_h())).json()
    assert which["signature"] == "Sign B"

    # The supplied document's own signature picture is the place, found.
    spot = (await client.get(f"/api/admin/signatures/documents/{CODE}", headers=_h())).json()
    assert spot["spot"] == sr.default_spot() and spot["found"] and not spot["chosen"]
    assert any(p["checksum"] == spot["spot"][8:] for p in spot["pictures"])
    pic = await client.get(f"/api/admin/signatures/documents/{CODE}/pictures/{spot['spot'][8:]}",
                           headers=_h())
    assert pic.status_code == 200 and pic.content

    # The real path (template test run) carries Sign A.
    r = await client.post(f"/api/admin/templates/{CODE}/test", headers=_h(),
                          json={"csp_id": "SIGTEST1"})
    assert r.status_code == 200, r.text
    sign_a = (await client.get(f"/api/admin/signatures/{a['id']}/picture", headers=_h())).content
    assert sr.sha256(sign_a) in _blobs(r.content)

    # A picture in use cannot be removed; the rule can, then the picture.
    assert (await client.delete(f"/api/admin/signatures/{a['id']}", headers=_h())).status_code == 409
    rid = over["rules"][0]["id"]
    assert (await client.delete(f"/api/admin/signatures/rules/{rid}", headers=_h())).status_code == 200
    assert (await client.delete(f"/api/admin/signatures/{a['id']}", headers=_h())).status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_choosing_the_place_and_refusing_what_is_not_in_the_file(client, clean):
    r = await client.put(f"/api/admin/signatures/documents/{CODE}/spot", headers=_h(),
                         json={"spot": "picture:" + "0" * 64})
    assert r.status_code == 400
    r = await client.put(f"/api/admin/signatures/documents/{CODE}/spot", headers=_h(),
                         json={"spot": "text:no such line anywhere"})
    assert r.status_code == 400
    info = (await client.get(f"/api/admin/signatures/documents/{CODE}", headers=_h())).json()
    line = info["paragraphs"][0]["text"]
    r = await client.put(f"/api/admin/signatures/documents/{CODE}/spot", headers=_h(),
                         json={"spot": "text:" + line})
    assert r.status_code == 200, r.text
    info = (await client.get(f"/api/admin/signatures/documents/{CODE}", headers=_h())).json()
    assert info["chosen"] and info["found"] and info["spot"].startswith("text:")
    r = await client.put(f"/api/admin/signatures/documents/{CODE}/spot", headers=_h(),
                         json={"spot": None})
    assert r.status_code == 200
    info = (await client.get(f"/api/admin/signatures/documents/{CODE}", headers=_h())).json()
    assert not info["chosen"] and info["spot"] == sr.default_spot()


@pytest.mark.asyncio(loop_scope="session")
async def test_an_rm_cannot_reach_signatures(client, clean):
    rm = _h("rm", "sig.rm@eko.co.in")
    assert (await client.get("/api/admin/signatures", headers=rm)).status_code == 403
    assert (await client.post("/api/admin/signatures/rules", headers=rm,
                              json={"column": "", "signature_id": "00000000-0000-0000-0000-000000000000"})
            ).status_code == 403
