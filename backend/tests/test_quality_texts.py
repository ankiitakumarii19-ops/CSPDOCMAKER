# -*- coding: utf-8 -*-
"""Context, Harness and Guardrails in words, editable; "Upload document"
fills them for review (No. 171).

The live columns stay the code's; the words are the workspace's. A save
rewrites the chat's answer. An uploaded file is split by its headings with
fixed rules — nothing is saved until the person saves.
"""

import io

import pytest
from sqlalchemy import select

from app.models.knowledge import KnowledgeEntry
from app.models.workspace import Workspace
from app.services import jwt_service, quality_texts, quality_upload
from app.workspace_context import all_workspaces
from tests.conftest import DEFAULT_WORKSPACE_ID

on_loop = pytest.mark.asyncio(loop_scope="session")

QUESTIONS = (quality_texts.Q_CONTEXT, quality_texts.Q_HARNESS,
             quality_texts.Q_GUARDRAILS)


def _auth(role="admin"):
    token = jwt_service.create_access_token(
        {"sub": f"{role}@eko.co.in", "role": role, "name": role})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def restore(db):
    """Put the workspace's words and the three chat answers back."""
    with all_workspaces():
        ws = (await db.execute(select(Workspace).where(
            Workspace.id == DEFAULT_WORKSPACE_ID))).scalars().one()
        settings = dict(ws.settings or {})
        entries = {e.question: e.answer for e in (await db.execute(
            select(KnowledgeEntry).where(
                KnowledgeEntry.workspace_id == DEFAULT_WORKSPACE_ID,
                KnowledgeEntry.question.in_(QUESTIONS)))).scalars()}
    yield
    with all_workspaces():
        db.expire_all()
        ws = (await db.execute(select(Workspace).where(
            Workspace.id == DEFAULT_WORKSPACE_ID))).scalars().one()
        ws.settings = settings
        for e in (await db.execute(select(KnowledgeEntry).where(
                KnowledgeEntry.workspace_id == DEFAULT_WORKSPACE_ID,
                KnowledgeEntry.question.in_(QUESTIONS)))).scalars():
            if e.question in entries:
                e.answer = entries[e.question]
            else:
                await db.delete(e)
        await db.commit()


async def _answer(db, question):
    with all_workspaces():
        db.expire_all()
        return (await db.execute(select(KnowledgeEntry.answer).where(
            KnowledgeEntry.workspace_id == DEFAULT_WORKSPACE_ID,
            KnowledgeEntry.question == question))).scalar()


# ---- the words, saved --------------------------------------------------------

@on_loop
async def test_the_code_words_show_until_someone_saves(client, restore):
    body = (await client.get("/api/admin/quality/texts",
                             headers=_auth())).json()
    csp = next(r for r in body["context"] if r["key"] == "csp")
    assert csp["label"] == "CSP sheet" and not csp["edited"]
    assert body["guardrails"][0]["title"] == "No AI anywhere"


@on_loop
async def test_context_words_are_saved_and_the_chat_answer_follows(
        client, db, restore):
    response = await client.put(
        "/api/admin/quality/texts/context", headers=_auth(),
        json={"items": [{"key": "csp", "label": "CSPDATA",
                         "used_for": "Every CSP's details, read every minute"}]})
    assert response.status_code == 200, response.text
    csp = next(r for r in response.json()["context"] if r["key"] == "csp")
    assert csp == {"key": "csp", "label": "CSPDATA",
                   "used_for": "Every CSP's details, read every minute",
                   "edited": True}
    answer = await _answer(db, quality_texts.Q_CONTEXT)
    assert "**CSPDATA** — Every CSP's details, read every minute" in answer
    assert "Zoho Lead" in answer, "what the table does not list stays"


@on_loop
async def test_harness_words_replace_the_codes_but_not_the_live_columns(
        client, db, restore):
    before = (await client.get("/api/admin/quality/harness",
                               headers=_auth())).json()["checks"]
    first = before[0]
    response = await client.put(
        "/api/admin/quality/texts/harness", headers=_auth(),
        json={"items": [{"key": first["key"], "name": "Filled-in values",
                         "watches": "What the app fills", "how": "Kept with why"}]})
    assert response.status_code == 200, response.text
    after = (await client.get("/api/admin/quality/harness",
                              headers=_auth())).json()["checks"]
    assert after[0]["name"] == "Filled-in values" and after[0]["edited"]
    assert after[0]["now"] == first["now"] and after[0]["state"] == first["state"]
    assert "**Filled-in values** — What the app fills" in await _answer(
        db, quality_texts.Q_HARNESS)


@on_loop
async def test_guardrails_are_saved_and_answered(client, db, restore):
    response = await client.put(
        "/api/admin/quality/texts/guardrails", headers=_auth("super_admin"),
        json={"items": [{"title": "No AI", "detail": "Rules only"},
                        {"title": "  ", "detail": "dropped: no title"}]})
    assert response.status_code == 200, response.text
    assert response.json()["guardrails"] == [{"title": "No AI", "detail": "Rules only"}]
    assert "1. **No AI** — Rules only" in await _answer(db, quality_texts.Q_GUARDRAILS)


@on_loop
async def test_an_unknown_row_is_refused(client, restore):
    response = await client.put(
        "/api/admin/quality/texts/context", headers=_auth(),
        json={"items": [{"key": "zoho_magic", "label": "x", "used_for": "y"}]})
    assert response.status_code == 400


@on_loop
async def test_an_rm_cannot_change_the_words(client, restore):
    response = await client.put(
        "/api/admin/quality/texts/guardrails", headers=_auth("rm"),
        json={"items": [{"title": "x", "detail": ""}]})
    assert response.status_code == 403


# ---- reading an uploaded file ---------------------------------------------

CONTEXT = [{"key": k, "label": quality_texts.CONTEXT_LABELS[k],
            "used_for": v} for k, v in quality_texts.CONTEXT_USED_FOR.items()]
HARNESS = [{"key": "auto_fill", "name": "Auto-fill record", "watches": "w",
            "how": "h"},
           {"key": "kept_rate", "name": "Kept rate", "watches": "w", "how": "h"}]

DOC = """# Context
CSP sheet: Every CSP, read every minute
Sign-in list - Who may sign in
Some sheet we do not read: anything

# Harness
Kept rate: Share of values nobody corrected
How: counted every night

# Guardrails
- Never use AI: rules only
- Never send after 8 pm

# Knowledge Base
## Documents
Q: Where are my documents?
A: In your email.
How do I change my photo?
Send a new one on WhatsApp.
"""


def test_a_text_file_is_split_by_its_headings():
    lines = quality_upload.read_lines("notes.txt", DOC.encode())
    found = quality_upload.split(lines, CONTEXT, HARNESS)
    assert {r["key"]: r["used_for"] for r in found["context"]} == {
        "csp": "Every CSP, read every minute",
        "authorization": "Who may sign in"}
    assert found["harness"] == [{"key": "kept_rate", "name": "Kept rate",
                                 "watches": "Share of values nobody corrected",
                                 "how": "counted every night"}]
    assert found["guardrails"] == [
        {"title": "Never use AI", "detail": "rules only"},
        {"title": "Never send after 8 pm", "detail": ""}]
    assert found["knowledge"] == [
        {"question": "Where are my documents?", "answer": "In your email.",
         "category": "Documents"},
        {"question": "How do I change my photo?",
         "answer": "Send a new one on WhatsApp.", "category": "Documents"}]
    assert found["unplaced"] == ["Some sheet we do not read: anything"], \
        "a sheet the app does not read cannot be added in words"


def test_a_word_file_uses_its_heading_styles():
    from docx import Document

    doc = Document()
    doc.add_heading("Guardrails", level=1)
    doc.add_paragraph("Never mail an existing CSP")
    doc.add_heading("FAQ", level=1)
    doc.add_paragraph("What is a KO?")
    doc.add_paragraph("A code of 8 characters.")
    buf = io.BytesIO()
    doc.save(buf)
    found = quality_upload.split(
        quality_upload.read_lines("rules.docx", buf.getvalue()), CONTEXT, HARNESS)
    assert found["guardrails"] == [{"title": "Never mail an existing CSP", "detail": ""}]
    assert found["knowledge"][0]["question"] == "What is a KO?"
    assert found["knowledge"][0]["answer"] == "A code of 8 characters."


def test_a_pdf_is_read():
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Guardrails")
    page.insert_text((72, 100), "No payment or billing")
    data = pdf.tobytes()
    found = quality_upload.split(
        quality_upload.read_lines("rules.pdf", data), CONTEXT, HARNESS)
    assert found["guardrails"] == [{"title": "No payment or billing", "detail": ""}]


@pytest.mark.parametrize("name,data,message", [
    ("photo.png", b"x", "PDF, Word"),
    ("empty.txt", b"", "empty"),
    ("fake.pdf", b"not a pdf", "could not be read"),
])
def test_unreadable_files_say_why(name, data, message):
    with pytest.raises(quality_upload.UploadError) as e:
        quality_upload.read_lines(name, data)
    assert message in str(e.value)


@on_loop
async def test_upload_returns_a_preview_and_saves_nothing(client, db, restore):
    response = await client.post(
        "/api/admin/quality/texts/extract", headers=_auth(),
        files={"file": ("notes.txt", DOC.encode(), "text/plain")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["file"] == "notes.txt" and body["headings_found"]
    assert len(body["guardrails"]) == 2 and len(body["knowledge"]) == 2
    texts = (await client.get("/api/admin/quality/texts", headers=_auth())).json()
    assert texts["guardrails"][0]["title"] == "No AI anywhere", "nothing saved"
