"""The ask-anything chat (tracker No. 114).

The AI model is replaced by a script here — the suite never calls Cloudflare
or Google. What is tested is everything around it: RMs reach only their own
CSPs, cards come from the database, drafts send nothing until Send, a draft
is sent once and only by the person who made it, failures are reported
honestly, and every send is audited.
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
from app.models.whatsapp_message import WhatsAppMessage
from app.services import assistant_llm, assistant_tools, whatsapp_platform
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


class Script:
    """Stands in for the AI model: asks for the given tool calls, one round
    each, then answers with `reply`. Keeps what it was shown."""

    def __init__(self, *rounds, reply="Done."):
        self.rounds = list(rounds)
        self.reply = reply
        self.seen = []

    def __call__(self, messages, tools=None):
        self.seen.append(json.loads(json.dumps(messages)))
        if self.rounds:
            calls = self.rounds.pop(0)
            return {"content": None, "tool_calls": [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": n, "arguments": json.dumps(a)}}
                for i, (n, a) in enumerate(calls)]}
        return {"content": self.reply}

    def tool_results(self):
        return [json.loads(m["content"]) for m in self.seen[-1]
                if m["role"] == "tool"]


def _script(monkeypatch, *rounds, reply="Done."):
    s = Script(*rounds, reply=reply)
    monkeypatch.setattr(assistant_llm, "complete", s)
    return s


async def _ask(client, question, role="super_admin", who=None):
    return await client.post("/api/assistant/chat", headers=_auth(role, who),
                             json={"messages": [{"role": "user",
                                                 "content": question}]})


# ---- who may ask, and about whom -------------------------------------------

async def test_nobody_signed_out_can_use_the_chat(client, csps):
    r = await client.post("/api/assistant/chat",
                          json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 401


async def test_the_rbo_contact_comes_from_the_record(client, csps, monkeypatch):
    s = _script(monkeypatch, [("csp_details", {"csp_code": MINE})],
                reply="The RBO contact is 0612-555001.")
    r = await _ask(client, f"rbo contact of {MINE}?")
    assert r.status_code == 200, r.text
    body = r.json()
    card = body["cards"][0]
    assert card["type"] == "csp" and card["csp_code"] == MINE
    fields = {f["label"]: f["value"] for f in card["fields"]}
    assert fields["RBO Contact No."] == "0612-555001"
    assert s.tool_results()[0]["RBO Contact No."] == "0612-555001"


async def test_an_rm_gets_only_their_own_csps(client, csps, monkeypatch):
    s = _script(monkeypatch, [("csp_details", {"csp_code": THEIRS})])
    r = await _ask(client, "details", role="rm", who="rm1")
    assert r.status_code == 200 and r.json()["cards"] == []
    # Same words as for a CSP that does not exist: nothing is given away.
    assert s.tool_results()[0] == {
        "error": f"No CSP with code {THEIRS} was found among your CSPs."}

    _script(monkeypatch, [("csp_details", {"csp_code": MINE}),
                          ("csp_details", {"csp_code": NOBODYS})])
    r = await _ask(client, "details", role="rm", who="rm1")
    assert [c["csp_code"] for c in r.json()["cards"]] == [MINE, NOBODYS], \
        "own CSP and an unowned one are both visible to an RM"


async def test_search_respects_access_too(client, csps, monkeypatch):
    _script(monkeypatch, [("find_csps", {"query": "1A9100"})])
    r = await _ask(client, "list", role="rm", who="rm1")
    codes = {i["csp_code"] for i in r.json()["cards"][0]["items"]}
    assert codes == {MINE, NOBODYS, NO_MOBILE}

    _script(monkeypatch, [("find_csps", {"query": "1A9100"})])
    r = await _ask(client, "list", role="admin")
    assert r.json()["cards"][0]["total"] == 4


async def test_a_code_given_as_a_number_or_in_lower_case_is_found(
        client, csps, monkeypatch):
    _script(monkeypatch, [("csp_details", {"csp_code": MINE.lower()})])
    assert (await _ask(client, "x")).json()["cards"][0]["csp_code"] == MINE
    _script(monkeypatch, [("find_csps", {"query": 9100})])
    r = await _ask(client, "x")
    assert r.json()["cards"][0]["total"] == 4


async def test_bad_requests_from_the_model_go_back_to_it_not_to_a_crash(
        client, csps, monkeypatch):
    s = _script(monkeypatch, [("no_such_tool", {}),
                              ("csp_details", {}),
                              ("find_csps", {"query": "a"})])
    r = await _ask(client, "x")
    assert r.status_code == 200
    errors = [t["error"] for t in s.tool_results()]
    assert "no tool called" in errors[0]
    assert errors[1] == "No CSP code was given."
    assert "two characters" in errors[2]


# ---- documents ----------------------------------------------------------------

async def test_documents_are_offered_latest_version_first(client, csps, monkeypatch):
    _script(monkeypatch, [("csp_documents", {"csp_code": MINE})])
    card = (await _ask(client, "docs")).json()["cards"][0]
    assert card["type"] == "documents"
    [doc] = card["documents"]
    assert doc["version"] == 2 and doc["versions"] == 2

    r = await client.get(f"/api/assistant/documents/{doc['id']}",
                         headers=_auth("rm", "rm1"))
    assert r.status_code == 200
    assert r.content == MINIMAL_PDF + b"%v2"
    assert r.headers["content-disposition"].startswith("attachment")


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


# ---- drafting and sending ------------------------------------------------------

async def _draft(client, monkeypatch, code=MINE, channel="auto",
                 message="Please visit the branch tomorrow.", **who):
    _script(monkeypatch, [("draft_message", {
        "csp_code": code, "message": message, "channel": channel})],
        reply="Check the draft and press Send.")
    role, name = who.get("role", "super_admin"), who.get("who")
    r = await _ask(client, "remind them", role=role, who=name)
    assert r.status_code == 200, r.text
    return r.json()["cards"]


async def test_a_draft_sends_nothing(client, csps, monkeypatch):
    sent = []
    monkeypatch.setattr(whatsapp_platform, "send",
                        lambda *a, **k: sent.append(a))
    [card] = await _draft(client, monkeypatch)
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
    [card] = await _draft(client, monkeypatch)

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
    [card] = await _draft(client, monkeypatch)
    r = await client.post(f"/api/assistant/drafts/{card['id']}/send",
                          headers=_auth("super_admin"))
    body = r.json()
    assert body["state"] == "pending" and "NOT been delivered" in body["reason"]


async def test_a_failed_send_can_be_tried_again(client, csps, monkeypatch):
    outcomes = [{"status": whatsapp_platform.FAILED, "reason": "platform down"},
                {"status": whatsapp_platform.SENT, "reason": ""}]
    monkeypatch.setattr(whatsapp_platform, "send",
                        lambda *a, **k: outcomes.pop(0))
    [card] = await _draft(client, monkeypatch)
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
    [card] = await _draft(client, monkeypatch, role="rm", who="rm1")
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
    [card] = await _draft(client, monkeypatch, role="rm", who="rm1")
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
    [card] = await _draft(client, monkeypatch, code=NO_MOBILE)
    assert card["channel"] == "email" and card["to"] == "only@example.com"
    r = await client.post(f"/api/assistant/drafts/{card['id']}/send",
                          headers=_auth("super_admin"))
    assert r.json()["state"] == "sent"
    [(to, subject, body)] = mails
    assert NO_MOBILE in subject and body == card["preview"]
    assert "Please visit the branch tomorrow." in body


async def test_unreachable_and_oversized_drafts_are_refused(
        client, csps, monkeypatch):
    s = _script(monkeypatch, [
        ("draft_message", {"csp_code": THEIRS, "message": "hi",
                           "channel": "email"}),
        ("draft_message", {"csp_code": MINE, "message": "x" * 901}),
        ("draft_message", {"csp_code": MINE, "message": "  "}),
        ("draft_message", {"csp_code": MINE, "message": "hi",
                           "channel": "sms"})])
    r = await _ask(client, "x")
    assert r.json()["cards"] == []
    errors = [t["error"] for t in s.tool_results()]
    assert "no usable email address; whatsapp is possible instead" in errors[0]
    assert "keep it under 900" in errors[1]
    assert "empty" in errors[2]
    assert "Unknown channel" in errors[3]


async def test_cancel_removes_the_draft(client, csps, monkeypatch):
    [card] = await _draft(client, monkeypatch)
    r = await client.delete(f"/api/assistant/drafts/{card['id']}",
                            headers=_auth("super_admin"))
    assert r.status_code == 200
    r = await client.post(f"/api/assistant/drafts/{card['id']}/send",
                          headers=_auth("super_admin"))
    assert r.status_code == 404
    r = await client.post("/api/assistant/drafts/not-hex/send",
                          headers=_auth("super_admin"))
    assert r.status_code == 404


# ---- when the AI model fails ----------------------------------------------------

async def test_an_ai_failure_is_reported_not_hidden(client, csps, monkeypatch):
    def down(messages, tools=None):
        raise assistant_llm.AssistantUnavailable(
            "The AI model did not answer (cloudflare, TimeoutException: x)")
    monkeypatch.setattr(assistant_llm, "complete", down)
    r = await _ask(client, "hello")
    assert r.status_code == 503
    assert "did not answer" in r.json()["detail"]


async def test_a_model_that_never_stops_asking_is_cut_off(client, csps, monkeypatch):
    _script(monkeypatch, *[[("find_csps", {"query": "Patna"})]] * 10)
    r = await _ask(client, "x")
    assert r.status_code == 200 and "could not finish" in r.json()["reply"]


async def test_the_last_message_must_be_a_question(client, csps):
    r = await client.post("/api/assistant/chat", headers=_auth("admin"),
                          json={"messages": [{"role": "assistant",
                                              "content": "hi"}]})
    assert r.status_code == 422


async def test_provider_settings_are_explained(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "assistant_provider", "cloudflare")
    monkeypatch.setattr(s, "cloudflare_account_id", "")
    with pytest.raises(assistant_llm.AssistantUnavailable,
                       match="CLOUDFLARE_ACCOUNT_ID"):
        assistant_llm.complete([])
    monkeypatch.setattr(s, "assistant_provider", "off")
    with pytest.raises(assistant_llm.AssistantUnavailable, match="switched off"):
        assistant_llm.complete([])
    monkeypatch.setattr(s, "assistant_provider", "openai")
    with pytest.raises(assistant_llm.AssistantUnavailable, match="not one of"):
        assistant_llm.complete([])


@pytest.mark.parametrize("status_code,payload,match", [
    (500, {"error": "boom"}, "HTTP 500"),
    (429, {"error": "slow down"}, "HTTP 429"),
    (200, {"no": "choices"}, "unreadable answer"),
])
async def test_bad_answers_from_the_provider_are_reported(
        monkeypatch, status_code, payload, match):
    import httpx
    s = get_settings()
    monkeypatch.setattr(s, "assistant_provider", "cloudflare")
    monkeypatch.setattr(s, "cloudflare_account_id", "acct")
    monkeypatch.setattr(s, "cloudflare_api_token", "tok")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(
        status_code, json=payload, request=httpx.Request("POST", "http://x")))
    with pytest.raises(assistant_llm.AssistantUnavailable, match=match):
        assistant_llm.complete([{"role": "user", "content": "hi"}])


async def test_a_network_failure_is_reported(monkeypatch):
    import httpx
    s = get_settings()
    monkeypatch.setattr(s, "assistant_provider", "cloudflare")
    monkeypatch.setattr(s, "cloudflare_account_id", "acct")
    monkeypatch.setattr(s, "cloudflare_api_token", "tok")

    def timeout(*a, **k):
        raise httpx.ReadTimeout("timed out")
    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(assistant_llm.AssistantUnavailable,
                       match="ReadTimeout") as info:
        assistant_llm.complete([{"role": "user", "content": "hi"}])
    assert isinstance(info.value.__cause__, httpx.ReadTimeout)


async def test_a_repeated_lookup_or_draft_shows_one_card(client, csps, monkeypatch):
    sent = []
    monkeypatch.setattr(whatsapp_platform, "send", lambda *a, **k: sent.append(1)
                        or {"status": whatsapp_platform.SENT, "reason": ""})
    _script(monkeypatch,
            [("csp_details", {"csp_code": MINE})],
            [("csp_details", {"csp_code": MINE})],
            [("draft_message", {"csp_code": MINE, "message": "First"})],
            [("draft_message", {"csp_code": MINE, "message": "Second"})])
    made = []
    real_save = assistant_tools.save_draft

    async def spy(draft, minutes):
        made.append(draft["id"])
        await real_save(draft, minutes)
    monkeypatch.setattr(assistant_tools, "save_draft", spy)
    cards = (await _ask(client, "x")).json()["cards"]
    assert [c["type"] for c in cards] == ["csp", "draft"]
    assert "Second." in cards[1]["preview"]
    assert len(made) == 2 and cards[1]["id"] == made[1]
    # The discarded first draft cannot be sent behind the person's back.
    r = await client.post(f"/api/assistant/drafts/{made[0]}/send",
                          headers=_auth("super_admin"))
    assert r.status_code == 404 and sent == []


async def test_the_message_is_finished_with_a_full_stop(client, csps, monkeypatch):
    [card] = await _draft(client, monkeypatch, message="Send your photo by Friday")
    assert "Send your photo by Friday. Thank you." in card["preview"]
    [card] = await _draft(client, monkeypatch, message="Are you open today?")
    assert "Are you open today? Thank you." in card["preview"]
