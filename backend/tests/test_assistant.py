"""The ask-anything chat (tracker No. 114; no AI model since No. 116).

Real questions are asked and the answers checked: they come from the
records and the Knowledge Base, the same question always gets the same
answer, RMs reach only their own CSPs, drafts send nothing until Send, a
draft is sent once and only by the person who made it, failures are
reported honestly, and every send is audited.
Test data only: invented CSPs, no real agents.
"""

import hashlib
import json

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.audit_log import AuditLog
from app.models.csp_record import CSPRecord
from app.models.enums import DocumentFormat, DocumentType
from app.models.stored_document import StoredDocument
from app.models.knowledge import KnowledgeEntry, KnowledgeMiss
from app.models.whatsapp_message import WhatsAppMessage
from app.services import assistant_tools, whatsapp_platform
from tests.conftest import MINIMAL_PDF

pytestmark = pytest.mark.asyncio(loop_scope="session")

MINE, THEIRS, NOBODYS, NO_MOBILE = "1A910001", "1A910002", "1A910003", "1A910004"


def _auth(role, who=None):
    from app.services import jwt_service
    email = f"{who or role}@eko.co.in"
    token = jwt_service.create_access_token({
        "sub": email, "email": email, "role": role, "name": (who or role).title()})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _fresh_redis_client(monkeypatch):
    # Each test runs on the session loop; a client made on another loop
    # would not be usable, so start with none.
    monkeypatch.setattr(assistant_tools, "_redis", None)


@pytest.fixture
def csps(migrated_db):
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as s:
        s.execute(text("TRUNCATE stored_documents, csp_records, "
                       "whatsapp_messages, audit_logs RESTART IDENTITY CASCADE"))
        s.add_all([
            CSPRecord(csp_id=MINE, csp_code=MINE, name="Asha Devi",
                      mobile="9876500001", email="asha@example.com",
                      rbo_name="RBO Patna", rbo_contact="0612-555001",
                      district="Patna", state="Bihar",
                      rm_email="rm1@eko.co.in", rm_resolution="sheet"),
            CSPRecord(csp_id=THEIRS, csp_code=THEIRS, name="Ravi Kumar",
                      mobile="9876500002", rbo_contact="0612-555002",
                      rm_email="rm2@eko.co.in", rm_resolution="sheet"),
            CSPRecord(csp_id=NOBODYS, csp_code=NOBODYS, name="Unowned CSP",
                      mobile="9876500003", rm_resolution="unresolved"),
            CSPRecord(csp_id=NO_MOBILE, csp_code=NO_MOBILE, name="Email Only",
                      email="only@example.com", rm_email="rm1@eko.co.in",
                      rm_resolution="sheet"),
        ])
        for version, data in ((1, MINIMAL_PDF), (2, MINIMAL_PDF + b"%v2")):
            s.add(StoredDocument(
                csp_id=MINE, document_type=DocumentType.CSP_ID_CARD,
                file_format=DocumentFormat.PDF, version=version,
                filename=f"ID Card v{version}.pdf",
                content_type="application/pdf", file_data=data,
                file_size=len(data), checksum=hashlib.sha256(data).hexdigest()))
        s.add(StoredDocument(
            csp_id=THEIRS, document_type=DocumentType.BCP,
            file_format=DocumentFormat.PDF, version=1, filename="BCP.pdf",
            content_type="application/pdf", file_data=MINIMAL_PDF,
            file_size=len(MINIMAL_PDF),
            checksum=hashlib.sha256(MINIMAL_PDF).hexdigest()))
        s.commit()
        yield s
    engine.dispose()


@pytest.fixture
def knowledge(csps):
    """A small Knowledge Base of our own, so answers do not depend on the
    starting set the migration writes."""
    csps.execute(text("TRUNCATE knowledge_entries, knowledge_misses"))
    csps.add_all([
        KnowledgeEntry(category="Documents", question="What is a BCP?",
                       phrasings="bcp meaning\nbcp kya hai", keywords="bcp",
                       answer="The BCP is made only for a KO."),
        KnowledgeEntry(category="Photos",
                       question="What size is the photo on the documents?",
                       phrasings="photo size\npassport photo",
                       keywords="size, passport",
                       answer="Passport size: 35 x 45 mm."),
        KnowledgeEntry(category="Access", question="Who can log in to the app?",
                       phrasings="login access", keywords="login",
                       answer="Only people in the Authorization sheet."),
        KnowledgeEntry(category="Access", question="An old answer",
                       phrasings="retired entry", keywords="retired",
                       answer="Should never be given.", active=False),
    ])
    csps.commit()
    return csps


async def _ask(client, question, role="super_admin", who=None, history=()):
    messages = [{"role": r, "content": c} for r, c in history]
    messages.append({"role": "user", "content": question})
    return await client.post("/api/assistant/chat", headers=_auth(role, who),
                             json={"messages": messages})


async def _reply(client, question, **kw):
    r = await _ask(client, question, **kw)
    assert r.status_code == 200, r.text
    return r.json()


# ---- who may ask, and about whom -------------------------------------------

async def test_nobody_signed_out_can_use_the_chat(client, csps):
    r = await client.post("/api/assistant/chat",
                          json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 401


async def test_the_rbo_contact_comes_from_the_record(client, csps):
    body = await _reply(client, f"rbo contact of {MINE}?")
    assert "**RBO Contact No.**: 0612-555001" in body["reply"]
    assert "RBO Name" not in body["reply"], "only what was asked"
    [card] = body["cards"]
    assert card["type"] == "csp" and card["csp_code"] == MINE
    fields = {f["label"]: f["value"] for f in card["fields"]}
    assert fields["RBO Contact No."] == "0612-555001"

    body = await _reply(client, f"{MINE} ka RBO kaun hai")
    assert "RBO Patna" in body["reply"]


async def test_a_missing_value_is_said_to_be_missing(client, csps):
    body = await _reply(client, f"ASM email of {MINE}")
    assert "**ASM Email Id**: not on record" in body["reply"]


async def test_an_rm_gets_only_their_own_csps(client, csps):
    body = await _reply(client, f"details of {THEIRS}", role="rm", who="rm1")
    assert body["cards"] == []
    # Same words as for a CSP that does not exist: nothing is given away.
    assert body["reply"] == f"No CSP with code {THEIRS} was found among your CSPs."
    for code in (MINE, NOBODYS):
        body = await _reply(client, f"details of {code}", role="rm", who="rm1")
        assert body["cards"][0]["csp_code"] == code, \
            "own CSP and an unowned one are both visible to an RM"


async def test_part_of_a_code_lists_the_matches_within_access(client, csps):
    body = await _reply(client, "details of 1A9100", role="rm", who="rm1")
    codes = {i["csp_code"] for i in body["cards"][0]["items"]}
    assert codes == {MINE, NOBODYS, NO_MOBILE}
    body = await _reply(client, "details of 1A9100", role="admin")
    assert body["cards"][0]["total"] == 4


async def test_a_code_in_lower_case_and_an_unknown_code(client, csps):
    body = await _reply(client, f"mobile of {MINE.lower()}")
    assert "9876500001" in body["reply"]
    body = await _reply(client, "documents of 1A999999")
    assert body["reply"] == "No CSP with code 1A999999 was found."
    assert body["cards"] == []


async def test_a_csp_can_be_named_instead_of_coded(client, csps):
    body = await _reply(client, "documents of Asha Devi")
    assert body["cards"][0]["type"] == "documents"
    assert body["cards"][0]["csp_code"] == MINE


async def test_a_follow_up_question_uses_the_csp_just_discussed(client, csps):
    earlier = [("user", f"details of {MINE}"),
               ("assistant", f"Here is what is on record for Asha Devi ({MINE}).")]
    body = await _reply(client, "and his RBO number?", history=earlier)
    assert "0612-555001" in body["reply"]
    body = await _reply(client, "documents?", history=earlier)
    assert body["cards"][0]["type"] == "documents"


async def test_missing_details_and_photo_are_listed(client, csps):
    body = await _reply(client, f"what is missing for {MINE}?")
    assert body["reply"].startswith(f"Missing for Asha Devi ({MINE}):")
    assert "**Photo**: not on file" in body["reply"]
    body = await _reply(client, f"is the photo of {MINE} on file?")
    assert body["reply"].startswith(f"No photo of Asha Devi ({MINE}) is on file")


async def test_ko_level_and_email_delivery(client, csps):
    body = await _reply(client, f"is {MINE} a KO or Sub KO?")
    assert body["reply"] == f"Asha Devi ({MINE}) is a **KO**."
    body = await _reply(client, f"were the documents of {MINE} mailed?")
    assert body["reply"].startswith(f"Email delivery for Asha Devi ({MINE}):")
    assert "**CSP ID Card**: not emailed yet" in body["reply"]


async def test_whatsapp_status_comes_from_the_message_log(client, csps):
    body = await _reply(client, f"WhatsApp status of {MINE}")
    assert body["reply"] == f"No WhatsApp to Asha Devi ({MINE}) is on record."
    csps.add(WhatsAppMessage(csp_id=MINE, csp_name="Asha Devi",
                             phone="919876500001", kind="missing_data",
                             send_status="sent", delivery_status="read"))
    csps.commit()
    body = await _reply(client, f"did {MINE} read the whatsapp?")
    assert "**Data missing**" in body["reply"] and ": read" in body["reply"]


# ---- documents ----------------------------------------------------------------

async def test_documents_are_offered_latest_version_first(client, csps):
    body = await _reply(client, f"Do you have the documents of CSP {MINE}?")
    assert body["reply"].startswith(
        f"Yes — 1 document stored for Asha Devi ({MINE})")
    card = body["cards"][0]
    assert card["type"] == "documents"
    [doc] = card["documents"]
    assert doc["version"] == 2 and doc["versions"] == 2

    r = await client.get(f"/api/assistant/documents/{doc['id']}",
                         headers=_auth("rm", "rm1"))
    assert r.status_code == 200
    assert r.content == MINIMAL_PDF + b"%v2"
    assert r.headers["content-disposition"].startswith("attachment")


async def test_no_documents_is_said_plainly(client, csps):
    body = await _reply(client, f"{NO_MOBILE} ke documents")
    assert body["reply"].startswith(
        f"No documents are stored for Email Only ({NO_MOBILE}) yet.")


async def test_an_rm_cannot_download_another_rms_document(client, csps):
    doc = csps.execute(select(StoredDocument).where(
        StoredDocument.csp_id == THEIRS)).scalars().one()
    r = await client.get(f"/api/assistant/documents/{doc.id}",
                         headers=_auth("rm", "rm1"))
    assert r.status_code == 404
    r = await client.get(f"/api/assistant/documents/{doc.id}",
                         headers=_auth("admin"))
    assert r.status_code == 200
    for bad in ("not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        r = await client.get(f"/api/assistant/documents/{bad}",
                             headers=_auth("admin"))
        assert r.status_code == 404


async def test_a_tampered_document_is_refused(client, csps):
    doc = csps.execute(select(StoredDocument).where(
        StoredDocument.csp_id == THEIRS)).scalars().one()
    doc.file_data = b"changed"
    csps.commit()
    r = await client.get(f"/api/assistant/documents/{doc.id}",
                         headers=_auth("admin"))
    assert r.status_code == 409


# ---- counts and lists -----------------------------------------------------------

async def test_counts_and_lists(client, csps):
    body = await _reply(client, "how many CSPs?", role="admin")
    assert body["reply"] == "**4** CSPs."
    body = await _reply(client, "how many CSPs?", role="rm", who="rm1")
    assert body["reply"] == "**3** CSPs of yours."
    body = await _reply(client, "how many CSPs in Patna?", role="admin")
    assert body["reply"].startswith("**1** CSP matching “patna”")
    assert body["cards"][0]["items"][0]["csp_code"] == MINE
    body = await _reply(client, "list CSPs without photo", role="admin")
    assert body["reply"] == "**4** CSPs without a photo."
    body = await _reply(client, "kitne CSPs ke documents nahi hai", role="admin")
    assert body["reply"] == "**2** CSPs with no documents stored."


# ---- the Knowledge Base -----------------------------------------------------------

async def test_process_questions_come_from_the_knowledge_base(client, knowledge):
    for q in ("What is a BCP?", "bcp kya hai", "BCP meaning please"):
        body = await _reply(client, q)
        assert body["reply"] == "The BCP is made only for a KO.", q
    body = await _reply(client, "what size should the passport photo be")
    assert body["reply"] == "Passport size: 35 x 45 mm."


async def test_a_definition_is_not_mistaken_for_the_last_csp(client, knowledge):
    earlier = [("user", f"details of {MINE}"),
               ("assistant", f"Here is what is on record for Asha Devi ({MINE}).")]
    body = await _reply(client, "What is a BCP?", history=earlier)
    assert body["reply"] == "The BCP is made only for a KO."


async def test_a_switched_off_entry_is_never_given(client, knowledge):
    body = await _reply(client, "retired entry")
    assert "Should never be given" not in body["reply"]


async def test_the_same_question_always_gets_the_same_answer(client, knowledge):
    first = await _reply(client, f"RBO number of {MINE}")
    for _ in range(3):
        assert await _reply(client, f"RBO number of {MINE}") == first
    first = await _reply(client, "who can login")
    assert first["reply"] == "Only people in the Authorization sheet."
    assert await _reply(client, "who can login") == first


async def test_an_unanswered_question_is_noted_for_an_admin(client, knowledge):
    body = await _reply(client, "What is the weather on Sunday?")
    assert body["reply"].startswith("Sorry, I don't have an answer to that yet.")
    await _reply(client, "what is the WEATHER on sunday")
    knowledge.expire_all()
    [miss] = knowledge.execute(select(KnowledgeMiss)).scalars().all()
    assert miss.times_asked == 2 and miss.normalized == "weather sunday"


async def test_hello_explains_what_can_be_asked(client, knowledge):
    body = await _reply(client, "hi")
    assert "no AI" in body["reply"] and body["suggestions"]


# ---- drafting and sending ------------------------------------------------------

async def _draft(client, code=MINE, message="Please visit the branch tomorrow.",
                 **who):
    role, name = who.get("role", "super_admin"), who.get("who")
    body = await _reply(client, f"Message {code}: {message}", role=role,
                        who=name)
    return body["cards"]


async def test_own_words_and_fixed_wordings(client, csps):
    body = await _reply(client, f"Remind CSP {MINE} to send their photo by Friday")
    assert "Please send your photo by Friday. Thank you." in \
        body["cards"][0]["preview"]
    assert "(a fixed wording)" not in body["reply"]
    body = await _reply(client, f"remind {MINE} about photo")
    assert "clear, recent photo" in body["cards"][0]["preview"]
    assert "(a fixed wording)" in body["reply"]
    body = await _reply(client, f"remind {MINE} for missing details")
    assert "still missing" in body["cards"][0]["preview"]


async def test_a_documents_ready_message_needs_the_documents_emailed(client, csps):
    body = await _reply(client, f"remind {MINE} that documents are ready")
    assert body["cards"] == []
    assert "have not been emailed yet" in body["reply"]


async def test_a_draft_needs_a_csp_and_words(client, csps):
    body = await _reply(client, "remind them to send the photo")
    assert body["reply"].startswith("Which CSP should get the message?")
    body = await _reply(client, f"Remind {MINE}")
    assert body["reply"].startswith("What should the message say?")


async def test_a_draft_sends_nothing(client, csps, monkeypatch):
    sent = []
    monkeypatch.setattr(whatsapp_platform, "send",
                        lambda *a, **k: sent.append(a))
    [card] = await _draft(client)
    assert card["type"] == "draft" and card["channel"] == "whatsapp"
    assert card["to"] == "919876500001"
    assert "Please visit the branch tomorrow." in card["preview"]
    assert card["preview"].startswith("Namaste Asha Devi")
    assert "owner" not in card and "workspace_id" not in card
    assert sent == []


async def test_send_delivers_once_and_is_audited(client, csps, monkeypatch):
    calls = []

    def fake_send(to, body, values, *, source_name, **k):
        calls.append((to, body, values, source_name))
        return {"status": whatsapp_platform.SENT, "reason": "",
                "job_id": "job-1", "template_name": "t1"}
    monkeypatch.setattr(whatsapp_platform, "send", fake_send)
    [card] = await _draft(client)

    r = await client.post(f"/api/assistant/drafts/{card['id']}/send",
                          headers=_auth("super_admin"))
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "sent"
    [(to, body, values, source)] = calls
    assert to == "919876500001" and body == assistant_tools.WHATSAPP_WORDING
    assert values == {"name": "Asha Devi",
                      "message": "Please visit the branch tomorrow."}

    again = await client.post(f"/api/assistant/drafts/{card['id']}/send",
                              headers=_auth("super_admin"))
    assert again.status_code == 404 and len(calls) == 1, "sent once only"

    csps.expire_all()
    audit = csps.execute(select(AuditLog).where(
        AuditLog.action == "assistant_message")).scalars().one()
    assert audit.csp_id == MINE and audit.result == "success"
    assert audit.metadata_json["by"] == "super_admin@eko.co.in"
    msg = csps.execute(select(WhatsAppMessage)).scalars().one()
    assert msg.csp_id == MINE and msg.job_id == "job-1"


async def test_the_whatsapp_wording_becomes_one_template(csps):
    template, mapping, columns = whatsapp_platform.to_template(
        assistant_tools.WHATSAPP_WORDING)
    assert "{{1}}" in template and "{{2}}" in template
    assert columns == ["name", "message"]
    assert not template.startswith("{{") and not template.endswith("}}")


async def test_waiting_for_whatsapp_approval_is_not_called_sent(
        client, csps, monkeypatch):
    monkeypatch.setattr(whatsapp_platform, "send", lambda *a, **k: {
        "status": whatsapp_platform.PENDING, "reason": "x", "job_id": "j",
        "template_name": "t"})
    [card] = await _draft(client)
    r = await client.post(f"/api/assistant/drafts/{card['id']}/send",
                          headers=_auth("super_admin"))
    body = r.json()
    assert body["state"] == "pending" and "NOT been delivered" in body["reason"]


async def test_a_failed_send_can_be_tried_again(client, csps, monkeypatch):
    outcomes = [{"status": whatsapp_platform.FAILED, "reason": "platform down"},
                {"status": whatsapp_platform.SENT, "reason": ""}]
    monkeypatch.setattr(whatsapp_platform, "send",
                        lambda *a, **k: outcomes.pop(0))
    [card] = await _draft(client)
    url = f"/api/assistant/drafts/{card['id']}/send"
    first = (await client.post(url, headers=_auth("super_admin"))).json()
    assert first["state"] == "failed" and first["reason"] == "platform down"
    second = (await client.post(url, headers=_auth("super_admin"))).json()
    assert second["state"] == "sent"
    csps.expire_all()
    results = sorted(a.result for a in csps.execute(select(AuditLog)).scalars())
    assert results == ["failure", "success"]


async def test_only_the_person_who_drafted_it_can_send_it(client, csps, monkeypatch):
    monkeypatch.setattr(whatsapp_platform, "send", lambda *a, **k: {
        "status": whatsapp_platform.SENT, "reason": ""})
    [card] = await _draft(client, role="rm", who="rm1")
    url = f"/api/assistant/drafts/{card['id']}/send"
    r = await client.post(url, headers=_auth("rm", "rm2"))
    assert r.status_code == 404
    r = await client.post(url, headers=_auth("rm", "rm1"))
    assert r.status_code == 200 and r.json()["state"] == "sent", \
        "the refused attempt did not use up the owner's draft"


async def test_access_is_checked_again_at_send_time(client, csps, monkeypatch):
    sent = []
    monkeypatch.setattr(whatsapp_platform, "send",
                        lambda *a, **k: sent.append(1))
    [card] = await _draft(client, role="rm", who="rm1")
    csp = csps.execute(select(CSPRecord).where(
        CSPRecord.csp_id == MINE)).scalars().one()
    csp.rm_email = "rm2@eko.co.in"  # reassigned in the meantime
    csps.commit()
    r = await client.post(f"/api/assistant/drafts/{card['id']}/send",
                          headers=_auth("rm", "rm1"))
    assert r.status_code == 404 and sent == []


async def test_email_is_used_when_there_is_no_mobile(client, csps, monkeypatch):
    from app.services import message_sender
    mails = []
    monkeypatch.setattr(message_sender, "_send_email",
                        lambda to, subject, body: mails.append(
                            (to, subject, body)) or (True, ""))
    [card] = await _draft(client, code=NO_MOBILE)
    assert card["channel"] == "email" and card["to"] == "only@example.com"
    r = await client.post(f"/api/assistant/drafts/{card['id']}/send",
                          headers=_auth("super_admin"))
    assert r.json()["state"] == "sent"
    [(to, subject, body)] = mails
    assert NO_MOBILE in subject and body == card["preview"]
    assert "Please visit the branch tomorrow." in body


async def test_unreachable_and_oversized_drafts_are_refused(client, csps):
    body = await _reply(client, f"Message {THEIRS} by email: hi there")
    assert body["cards"] == []
    assert "no usable email address; whatsapp is possible instead" in body["reply"]
    body = await _reply(client, f"Message {MINE}: " + "x" * 901)
    assert body["cards"] == [] and "keep it under 900" in body["reply"]


async def test_cancel_removes_the_draft(client, csps, monkeypatch):
    [card] = await _draft(client)
    r = await client.delete(f"/api/assistant/drafts/{card['id']}",
                            headers=_auth("super_admin"))
    assert r.status_code == 200
    r = await client.post(f"/api/assistant/drafts/{card['id']}/send",
                          headers=_auth("super_admin"))
    assert r.status_code == 404
    r = await client.post("/api/assistant/drafts/not-hex/send",
                          headers=_auth("super_admin"))
    assert r.status_code == 404


async def test_the_message_is_finished_with_a_full_stop(client, csps):
    [card] = await _draft(client, message="Send your photo by Friday")
    assert "Send your photo by Friday. Thank you." in card["preview"]
    [card] = await _draft(client, message="Are you open today?")
    assert "Are you open today? Thank you." in card["preview"]


# ---- Admin -> Knowledge Base ---------------------------------------------------------

async def test_only_admins_keep_the_knowledge_base(client, knowledge):
    r = await client.get("/api/admin/knowledge", headers=_auth("rm", "rm1"))
    assert r.status_code == 403
    r = await client.get("/api/admin/knowledge", headers=_auth("admin"))
    assert r.status_code == 200 and len(r.json()["entries"]) == 4


async def test_an_entry_is_added_changed_and_removed(client, knowledge):
    h = _auth("admin")
    r = await client.post("/api/admin/knowledge", headers=h, json={
        "question": "Who is the circle head of Bihar?",
        "phrasings": "bihar circle head", "keywords": "circle head",
        "answer": "Ask the RBO.", "category": "Contacts"})
    assert r.status_code == 201, r.text
    entry = r.json()
    body = await _reply(client, "circle head of bihar kaun hai")
    assert body["reply"] == "Ask the RBO."

    r = await client.put(f"/api/admin/knowledge/{entry['id']}", headers=h,
                         json={**entry, "answer": "Ask the LHO."})
    assert r.status_code == 200 and r.json()["updated_by"] == "admin@eko.co.in"
    assert (await _reply(client, "bihar circle head"))["reply"] == "Ask the LHO."

    r = await client.delete(f"/api/admin/knowledge/{entry['id']}", headers=h)
    assert r.status_code == 200
    assert (await _reply(client, "bihar circle head"))["reply"] != "Ask the LHO."
    knowledge.expire_all()
    actions = sorted(a.action for a in knowledge.execute(select(AuditLog)).scalars())
    assert actions == ["knowledge_add", "knowledge_change", "knowledge_delete"]


async def test_blank_entries_and_unknown_ids_are_refused(client, knowledge):
    h = _auth("admin")
    r = await client.post("/api/admin/knowledge", headers=h,
                          json={"question": "  ", "answer": "x"})
    assert r.status_code == 422
    for bad in ("nope", "00000000-0000-0000-0000-000000000000"):
        r = await client.delete(f"/api/admin/knowledge/{bad}", headers=h)
        assert r.status_code == 404


async def test_an_answer_written_for_a_missed_question_clears_it(client, knowledge):
    await _reply(client, "Where is the Patna office?")
    h = _auth("super_admin")
    [miss] = (await client.get("/api/admin/knowledge/misses",
                               headers=h)).json()["misses"]
    assert miss["question"] == "Where is the Patna office?"
    r = await client.post("/api/admin/knowledge", headers=h, json={
        "question": miss["question"], "answer": "Exhibition Road, Patna.",
        "from_miss": miss["id"]})
    assert r.status_code == 201
    assert (await client.get("/api/admin/knowledge/misses",
                             headers=h)).json()["misses"] == []
    body = await _reply(client, "where is the patna office")
    assert body["reply"] == "Exhibition Road, Patna."


async def test_trying_a_question_shows_the_scores(client, knowledge):
    r = await client.post("/api/admin/knowledge/try", headers=_auth("admin"),
                          json={"question": "bcp kya hai"})
    best = r.json()["matches"][0]
    assert best["question"] == "What is a BCP?" and best["score"] >= 0.5
