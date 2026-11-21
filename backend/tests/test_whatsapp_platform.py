"""WhatsApp through Eko's WhatsApp Bulk Sender (tracker No. 78, 12 Oct 2026).

The platform is never contacted: its HTTP endpoint is replaced. What is
pinned is the contract with it (wording, numbers, answers) and the guards
that stop a message going out when it should not.
"""

import json

import pytest

from app.services import whatsapp_platform as wa


# ---- wording -----------------------------------------------------------------

def test_each_placeholder_becomes_a_numbered_slot():
    body, mapping, columns = wa.to_template(
        "Namaste {name}, we need {fields}. Open {link} please, {name}.")
    assert body == "Namaste {{1}}, we need {{2}}. Open {{3}} please, {{4}}."
    assert mapping["1"] == {"type": "column", "value": "name"}
    assert mapping["4"] == {"type": "column", "value": "name"}
    assert columns == ["name", "fields", "link"]


def test_the_stored_wording_never_starts_or_ends_with_a_placeholder():
    """Meta refuses a template whose first or last thing is {{n}}."""
    from app.services import documents_whatsapp
    body, _, _ = wa.to_template(documents_whatsapp.BODY)
    assert not body.lstrip().startswith("{{")
    assert not body.rstrip().endswith("}}")


def test_a_value_never_carries_a_line_break():
    assert "\n" not in wa.one_line("Village Rampur\nDist Patna\r\nBihar")


@pytest.mark.parametrize("given,expected", [
    ("9876543210", "919876543210"),
    ("+91 98765 43210", "919876543210"),
    ("09876543210", "919876543210"),
    ("919876543210", "919876543210"),
    ("12345", ""),
    ("", ""),
])
def test_phone_numbers_get_the_country_code(given, expected):
    assert wa.phone_for_whatsapp(given) == expected


# ---- talking to the platform -------------------------------------------------

class _Reply:
    def __init__(self, result, status=200, sse=True):
        self.status_code = status
        payload = {"jsonrpc": "2.0", "id": 1, "result": result}
        self.text = ("event: message\ndata: " + json.dumps(payload)
                     if sse else json.dumps(payload))


def _tool(value):
    return {"content": [{"type": "text", "text": json.dumps(value)}],
            "isError": False}


@pytest.fixture
def platform(monkeypatch):
    """Replace the platform; script what smart_send_template answers."""
    calls = []
    script = {"send": {"action": "sent", "sent": 1, "failed": 0}}

    def post(url, json, headers, timeout):
        calls.append(json)
        name = json["params"]["name"]
        if name == "upload_contacts":
            return _Reply(_tool({"job_id": "job-1"}))
        return _Reply(_tool(script["send"]))

    import httpx
    monkeypatch.setattr(httpx, "post", post)
    return calls, script


def test_a_message_is_uploaded_then_sent(platform):
    calls, _ = platform
    out = wa.send("9876543210", "Namaste {name}, see {link} now.",
                  {"name": "Ravi\nKumar", "link": "https://x.in/a"},
                  source_name="test")
    assert out["status"] == wa.SENT and out["job_id"] == "job-1"
    upload, send = calls
    assert upload["params"]["arguments"]["contacts"] == [
        {"phone": "919876543210", "name": "Ravi / Kumar",
         "link": "https://x.in/a"}]
    args = send["params"]["arguments"]
    assert args["body"] == "Namaste {{1}}, see {{2}} now."
    assert args["phone_column"] == "phone" and args["category"] == "UTILITY"
    assert "header_type" not in args


def test_a_document_is_attached_by_its_public_link(platform):
    calls, _ = platform
    wa.send("9876543210", "Hi {name}, attached.", {"name": "R"},
            source_name="t", document_url="https://app.example.in/doc.pdf")
    args = calls[1]["params"]["arguments"]
    assert args["header_type"] == "document"
    assert args["header_media_url"] == "https://app.example.in/doc.pdf"


@pytest.mark.parametrize("answer,status", [
    ({"action": "created", "template_name": "auto_1"}, wa.PENDING),
    ({"action": "pending", "template_name": "auto_1"}, wa.PENDING),
    ({"action": "rejected", "reason": "wording"}, wa.REJECTED),
    ({"action": "sent", "sent": 0, "failed": 1}, wa.FAILED),
])
def test_every_platform_answer_is_reported_plainly(platform, answer, status):
    _, script = platform
    script["send"] = answer
    out = wa.send("9876543210", "Hi {name}, ok.", {"name": "R"},
                  source_name="t")
    assert out["status"] == status
    assert out["reason"] or status == wa.SENT


def test_an_unusable_number_is_never_sent(platform):
    calls, _ = platform
    out = wa.send("12345", "Hi {name}, ok.", {"name": "R"}, source_name="t")
    assert out["status"] == wa.FAILED and calls == []


def test_the_platform_being_down_is_a_failure_not_a_crash(monkeypatch):
    import httpx

    def down(*a, **k):
        raise httpx.ConnectError("no route")
    monkeypatch.setattr(httpx, "post", down)
    out = wa.send("9876543210", "Hi {name}, ok.", {"name": "R"},
                  source_name="t")
    assert out["status"] == wa.FAILED and "unreachable" in out["reason"]


# ---- the platform cannot find a template it made (No. 189) -------------------

_ALREADY = ("Error executing tool smart_send_template: There is already "
            "English (US) content for this template. You can create a new "
            "template and try again.")


@pytest.fixture
def lookup_missed(monkeypatch):
    """smart_send_template refuses with Meta's 'already exists'; script
    what send_template_message answers."""
    calls = []
    script = {"by_name": _tool({"sent": 1, "failed": 0, "skipped": 0}),
              "smart": {"content": [{"type": "text", "text": _ALREADY}],
                        "isError": True}}

    def post(url, json, headers, timeout):
        calls.append(json)
        name = json["params"]["name"]
        if name == "upload_contacts":
            return _Reply(_tool({"job_id": "job-1"}))
        return _Reply(script["smart" if name == "smart_send_template"
                             else "by_name"])

    import httpx
    monkeypatch.setattr(httpx, "post", post)
    return calls, script


def test_the_platform_names_a_wording_the_way_it_does():
    """Names seen on Eko's account on 17 Nov 2026."""
    from app.services import assistant_tools
    body, _, _ = wa.to_template(assistant_tools.WHATSAPP_WORDING)
    assert wa.platform_template_name(body) == "auto_e9c52b4a18ca16f9"
    assert (wa.platform_template_name("Hi {{1}},\n\n  ok.")
            == wa.platform_template_name("Hi {{1}}, ok."))


def test_a_template_the_platform_cannot_find_is_sent_by_its_name(
        lookup_missed):
    calls, _ = lookup_missed
    out = wa.send("9876543210", "Namaste {name}, see {link} now.",
                  {"name": "R", "link": "https://x.in/a"}, source_name="t")
    assert out["status"] == wa.SENT and out["reason"] == ""
    name = wa.platform_template_name("Namaste {{1}}, see {{2}} now.")
    assert out["template_name"] == name
    assert [c["params"]["name"] for c in calls] == [
        "upload_contacts", "smart_send_template", "send_template_message"]
    args = calls[2]["params"]["arguments"]
    assert args["template_name"] == name and args["job_id"] == "job-1"
    assert "body" not in args and "force" not in args
    assert args["mapping"] == {"1": {"type": "column", "value": "name"},
                               "2": {"type": "column", "value": "link"}}


def test_when_sending_by_name_also_fails_both_reasons_are_kept(
        lookup_missed):
    _, script = lookup_missed
    script["by_name"] = {"content": [{"type": "text",
                                      "text": "template not approved"}],
                         "isError": True}
    out = wa.send("9876543210", "Hi {name}, ok.", {"name": "R"},
                  source_name="t")
    assert out["status"] == wa.FAILED
    assert "already English (US) content" in out["reason"]
    assert "template not approved" in out["reason"]


def test_sending_by_name_that_sends_nobody_is_a_failure(lookup_missed):
    _, script = lookup_missed
    script["by_name"] = _tool({"sent": 0, "failed": 1})
    out = wa.send("9876543210", "Hi {name}, ok.", {"name": "R"},
                  source_name="t")
    assert out["status"] == wa.FAILED and "sent 0" in out["reason"]


def test_any_other_platform_error_is_not_sent_by_name(lookup_missed):
    calls, script = lookup_missed
    script["smart"] = {"content": [{"type": "text",
                                    "text": "Could not reach Meta API"}],
                       "isError": True}
    out = wa.send("9876543210", "Hi {name}, ok.", {"name": "R"},
                  source_name="t")
    assert out["status"] == wa.FAILED
    assert "send_template_message" not in [c["params"]["name"]
                                           for c in calls]


# ---- documents ready: the private link ---------------------------------------

def test_the_documents_link_is_signed_and_scoped():
    import uuid
    from app.services import documents_whatsapp as dw
    ws, job = uuid.uuid4(), uuid.uuid4()
    link = dw.link_for(ws, job, "1A850344")
    token = link.rsplit("/", 1)[1]
    claims = dw.read_link(token)
    assert claims["ws"] == str(ws) and claims["job"] == str(job)
    assert claims["csp"] == "1A850344"
    assert dw.read_link(token[:-2] + "xx") is None, "an altered link worked"


def test_an_ordinary_login_token_is_not_a_documents_link():
    from app.services import documents_whatsapp as dw, jwt_service
    access = jwt_service.create_access_token({"sub": "a@eko.co.in",
                                              "role": "rm"})
    assert dw.read_link(access) is None


def test_several_pdfs_become_one():
    import pymupdf
    from app.services import documents_whatsapp as dw

    def one_page(text):
        d = pymupdf.open(); d.new_page().insert_text((72, 72), text)
        try:
            return d.tobytes()
        finally:
            d.close()
    merged = dw.merged_pdf([one_page("a"), one_page("b"), one_page("c")])
    with pymupdf.open(stream=merged, filetype="pdf") as d:
        assert d.page_count == 3


def test_no_whatsapp_while_the_app_is_on_localhost(monkeypatch):
    """A laptop copy of the app never messages a CSP."""
    import uuid
    from types import SimpleNamespace
    from app.config import get_settings
    from app.services import documents_whatsapp as dw

    monkeypatch.setattr(get_settings(), "public_app_url",
                        "http://localhost:3000")
    monkeypatch.setattr(dw, "whatsapp_channel", lambda s: SimpleNamespace(
        last_used_at=None, last_error=None))
    sent = []
    monkeypatch.setattr(wa, "send", lambda *a, **k: sent.append(1))
    csp = SimpleNamespace(csp_id="1A850344", name="R", mobile="9876543210",
                          email="r@example.com")
    job = SimpleNamespace(workspace_id=uuid.uuid4(), id=uuid.uuid4())
    out = dw.notify(None, csp, job, ["CSP ID Card"])
    assert out["status"] == "skipped" and sent == []


def test_the_notice_says_they_were_emailed_and_carries_no_pdf(monkeypatch):
    """No. 135: the documents are not sent on WhatsApp, only the notice."""
    import uuid
    from types import SimpleNamespace
    from app.config import get_settings
    from app.services import documents_whatsapp as dw

    monkeypatch.setattr(get_settings(), "public_app_url",
                        "https://cspdocmaker.eko.in")
    channel = SimpleNamespace(last_used_at=None, last_error=None)
    monkeypatch.setattr(dw, "whatsapp_channel", lambda s: channel)
    seen = {}

    def fake_send(to, body, values, *, source_name, document_url=None,
                  category="UTILITY"):
        seen.update(to=to, values=values, url=document_url)
        return {"status": wa.SENT, "reason": "", "job_id": "j",
                "template_name": "t"}
    monkeypatch.setattr(wa, "send", fake_send)
    session = SimpleNamespace(commit=lambda: None)
    csp = SimpleNamespace(csp_id="1A850344", name="Ravi", mobile="9876543210",
                          email="r@example.com")
    job = SimpleNamespace(workspace_id=uuid.uuid4(), id=uuid.uuid4())
    out = dw.notify(session, csp, job, ["CSP ID Card", "BCP"])
    assert out["status"] == wa.SENT
    assert seen["url"] is None, "no PDF on WhatsApp"
    assert seen["values"]["documents"] == "CSP ID Card, BCP"
    assert seen["values"]["email"] == "r@example.com"
    assert "sent to your email {email}" in dw.BODY
    assert "attached" not in dw.BODY.lower()


def test_a_whatsapp_failure_never_raises(monkeypatch):
    from types import SimpleNamespace
    from app.services import documents_whatsapp as dw

    def boom(session):
        raise RuntimeError("database gone")
    monkeypatch.setattr(dw, "whatsapp_channel", boom)
    out = dw.notify(None, SimpleNamespace(csp_id="X"), None, [])
    assert out["status"] == "failed"


# ---- the public link, end to end ---------------------------------------------

@pytest.mark.asyncio(loop_scope="session")
async def test_the_link_serves_that_deliverys_pdfs_merged(client, db):
    import hashlib
    import uuid
    import pymupdf
    from app.models.csp_record import CSPRecord
    from app.models.enums import (
        DocumentFormat, DocumentType, JobState, WorkflowType,
    )
    from app.models.processing_job import ProcessingJob
    from app.models.stored_document import StoredDocument
    from app.services import documents_whatsapp as dw
    from tests.conftest import DEFAULT_WORKSPACE_ID

    def pdf(text):
        d = pymupdf.open(); d.new_page().insert_text((72, 72), text)
        try:
            return d.tobytes()
        finally:
            d.close()

    db.add(CSPRecord(csp_id="1A850999", csp_code="1A850999", name="Link"))
    job = ProcessingJob(job_id="JOB-LINK-1", csp_id="1A850999",
                        workflow_type=WorkflowType.EXISTING_CSP,
                        current_state=JobState.EMAIL_SENT)
    db.add(job)
    await db.flush()
    for dt in (DocumentType.CSP_ID_CARD, DocumentType.BCP):
        data = pdf(dt.value)
        db.add(StoredDocument(
            csp_id="1A850999", processing_job_id=job.id, document_type=dt,
            file_format=DocumentFormat.PDF, version=1,
            filename=f"{dt.value}.pdf", content_type="application/pdf",
            file_data=data, file_size=len(data),
            checksum=hashlib.sha256(data).hexdigest()))
    await db.commit()

    token = dw.link_for(DEFAULT_WORKSPACE_ID, job.id, "1A850999").rsplit("/", 1)[1]
    r = await client.get(f"/api/public/documents/{token}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    with pymupdf.open(stream=r.content, filetype="pdf") as d:
        assert d.page_count == 2

    other = dw.link_for(DEFAULT_WORKSPACE_ID, uuid.uuid4(), "1A850999").rsplit("/", 1)[1]
    assert (await client.get(f"/api/public/documents/{other}")).status_code == 404
    assert (await client.get("/api/public/documents/not-a-link")).status_code == 404


def test_a_message_a_person_sends_skips_the_15_minute_duplicate_block(platform):
    """No. 195: the platform refuses the same words to the same number within
    15 minutes. A person pressing Send means it, so it is sent anyway; the
    app's own messages keep that protection."""
    from app.services import send_reason
    calls, _ = platform
    wa.send("9876543210", "Namaste {name}, ok now.", {"name": "R"}, source_name="t")
    assert "force" not in calls[-1]["params"]["arguments"], "automatic: protected"
    with send_reason.sent_by("rm.one@eko.co.in"):
        wa.send("9876543210", "Namaste {name}, ok now.", {"name": "R"}, source_name="t")
    assert calls[-1]["params"]["arguments"]["force"] is True
    wa.send("9876543210", "Namaste {name}, ok now.", {"name": "R"},
            source_name="t", force=True)
    assert calls[-1]["params"]["arguments"]["force"] is True
