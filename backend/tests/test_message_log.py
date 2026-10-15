# -*- coding: utf-8 -*-
"""The record of every WhatsApp sent, and keeping it current (No. 110).

What matters:

  * every send is recorded — sent, refused or waiting — and recording can
    never break the send;
  * delivered / read / failed come from Meta's own report, per message;
  * an answer is matched to the right message: the form for a details ask,
    otherwise a WhatsApp reply from that number after that message;
  * the platform's history and inbox are shared with other Eko teams, so
    only this app's sends, for this workspace's CSPs, are taken;
  * a platform failure is reported, never swallowed, and never stops the
    rest of the refresh.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.data_request import ANSWERED, DataRequest
from app.models.messaging import (
    PURPOSE_DATA_REQUEST, PURPOSE_MISSING_DATA, WHATSAPP, MessageChannel,
    MessageTemplate,
)
from app.models.whatsapp_message import WhatsAppMessage
from app.services import message_log as log
from app.services import whatsapp_platform as wa
from app.workspace_context import workspace
from tests.conftest import DEFAULT_WORKSPACE_ID

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
SENT_OK = {"status": wa.SENT, "reason": "", "job_id": "job1",
           "template_name": "t1"}


@pytest.fixture(scope="module")
def _engine(migrated_db):
    engine = create_engine(
        get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"))
    yield engine
    engine.dispose()


@pytest.fixture
def db(_engine):
    with Session(_engine) as session:
        session.execute(text(
            "TRUNCATE whatsapp_messages, data_requests, message_channels, "
            "message_templates, csp_records RESTART IDENTITY CASCADE"))
        session.commit()
        with workspace(DEFAULT_WORKSPACE_ID):
            yield session


def _csp(session, csp_id="1A850001", mobile="9812345670", name="Asha"):
    record = CSPRecord(csp_id=csp_id, csp_code=csp_id, name=name,
                       origin="new", mobile=mobile, email="")
    session.add(record)
    session.commit()
    return record


def _message(session, **fields):
    values = dict(csp_id="1A850001", csp_name="Asha", phone="919812345670",
                  kind=log.KIND_DATA_REQUEST, send_status=wa.SENT,
                  job_id="job1", sent_at=NOW - timedelta(hours=1))
    values.update(fields)
    m = WhatsAppMessage(**values)
    session.add(m)
    session.commit()
    return m


class FakePlatform:
    """Eko's WhatsApp platform, answering as it really does."""

    def __init__(self, history="", inbox="", status=None, fail=()):
        self.history, self.inbox = history, inbox
        self.status = status or {}
        self.fail = set(fail)
        self.phone_for_whatsapp = wa.phone_for_whatsapp

    def call_tool(self, name, arguments):
        if name in self.fail:
            raise wa.WhatsAppPlatformError(f"{name} is down")
        if name == "get_send_history":
            return {"text": self.history}
        if name == "get_incoming_messages":
            return {"text": self.inbox}
        raise AssertionError(name)

    def delivery_status(self, job_id):
        if "get_delivery_status" in self.fail:
            raise wa.WhatsAppPlatformError("get_delivery_status is down")
        return self.status.get(job_id, {"rows": []})


def _delivery(status, sent_status="sent", error=""):
    return {"rows": [{"sent_status": sent_status, "delivery_status": status,
                      "delivery_error": error, "phone": "919812345670",
                      "delivery_updated_at": "2026-10-15T09:30:00+00:00"}]}


# ---- names on the platform -------------------------------------------------

def test_each_kind_has_a_name_that_reads_back():
    for kind in (log.KIND_DATA_REQUEST, log.KIND_MISSING_DATA,
                 log.KIND_DOCUMENTS_READY):
        for test in (False, True):
            if kind == log.KIND_DOCUMENTS_READY and test:
                continue
            name = log.source_name(kind, "1A850001", test=test)
            assert log.parse_source(name) == (kind, "1A850001", test)


def test_the_old_names_still_read_back():
    """Sends made before this change used these names."""
    assert log.parse_source("CSPdocMaker details request 1A852418") == (
        log.KIND_DATA_REQUEST, "1A852418", False)
    assert log.parse_source("CSPdocMaker documents 1A852418") == (
        log.KIND_DOCUMENTS_READY, "1A852418", False)


def test_other_teams_sends_are_not_ours():
    for name in ("csp-agent-UPLOAD_MISSING-2026", "whatsapp-nudges-2026-10",
                 "CSPdocMaker WhatsApp test", "", None,
                 "CSPdocMaker documents "):
        assert log.parse_source(name) is None


def test_the_platforms_back_to_back_json_is_read():
    assert log.json_objects('{"a": 1}{"b": 2}\n {"c": 3}') == [
        {"a": 1}, {"b": 2}, {"c": 3}]
    assert log.json_objects("") == []


def test_a_changed_answer_is_reported_not_read_as_nothing():
    with pytest.raises(ValueError):
        log.json_objects("Please log in again")


# ---- recording -------------------------------------------------------------

def test_a_send_is_recorded(db):
    m = log.record(db, kind=log.KIND_DATA_REQUEST, mobile="98123 45670",
                   outcome=SENT_OK, csp_id="1A850001", csp_name="Asha")
    db.commit()
    assert m is not None
    row = db.execute(select(WhatsAppMessage)).scalars().one()
    assert (row.phone, row.send_status, row.job_id) == (
        "919812345670", "sent", "job1")
    assert row.source == "app" and row.is_test is False


def test_a_refused_send_is_recorded_too(db):
    log.record(db, kind=log.KIND_DOCUMENTS_READY, mobile="9812345670",
               outcome={"status": wa.REJECTED, "reason": "Meta said no",
                        "job_id": None, "template_name": None},
               csp_id="1A850001")
    db.commit()
    row = db.execute(select(WhatsAppMessage)).scalars().one()
    assert row.send_status == "rejected" and row.send_error == "Meta said no"
    assert log.stage(row) == log.NOT_SENT
    assert "Rejected" in log.why(row)


def test_recording_can_never_break_the_send(db, caplog):
    log.record(db, kind=log.KIND_DATA_REQUEST, mobile="9812345670",
               outcome=SENT_OK)
    db.commit()
    # The same job id again breaks the unique rule — recording fails...
    assert log.record(db, kind=log.KIND_DATA_REQUEST, mobile="9812345670",
                      outcome=SENT_OK) is None
    assert "could not record" in caplog.text
    # ...and the caller's own work in the same session still commits.
    _csp(db, "1A850002")
    assert db.execute(select(CSPRecord)).scalars().one().csp_id == "1A850002"


def test_asking_on_whatsapp_records_which_message_it_was(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_app_url",
                        "https://csp.example.test")
    from app.services import message_sender as sender
    db.add(MessageChannel(name="WhatsApp", kind=WHATSAPP, provider="eko_wabs",
                          is_default=True))
    template = MessageTemplate(
        purpose=PURPOSE_MISSING_DATA, name="Missing", channel_kind=WHATSAPP,
        body="Namaste {name}, still needed: {fields}. Open {link} — Team")
    db.add(template)
    db.commit()
    record = _csp(db)
    names = []

    def fake_send(to, body, values, *, source_name, **_):
        names.append(source_name)
        return SENT_OK
    monkeypatch.setattr(wa, "send", fake_send)

    assert sender.ask_for_details(db, record, template=template)["sent"]
    row = db.execute(select(WhatsAppMessage)).scalars().one()
    request = db.execute(select(DataRequest)).scalars().one()
    assert row.kind == log.KIND_MISSING_DATA
    assert row.data_request_id == request.id
    assert names == ["CSPdocMaker details missing 1A850001"]


# ---- delivered / read --------------------------------------------------------

def test_read_and_delivered_come_from_metas_report(db):
    _message(db, job_id="a")
    _message(db, job_id="b")
    platform = FakePlatform(status={"a": _delivery("read"),
                                    "b": _delivery("delivered")})
    out = log.refresh(db, platform=platform, now=NOW)
    assert out["errors"] == [] and out["checked"] == 2
    stages = {m.job_id: log.stage(m, NOW)
              for m in db.execute(select(WhatsAppMessage)).scalars()}
    assert stages == {"a": log.READ, "b": log.DELIVERED}


def test_a_phone_that_could_not_be_reached_is_not_received(db):
    _message(db, job_id="a")
    log.refresh(db, platform=FakePlatform(
        status={"a": _delivery("failed", error="131026 not on WhatsApp")}),
        now=NOW)
    m = db.execute(select(WhatsAppMessage)).scalars().one()
    assert log.stage(m, NOW) == log.NOT_RECEIVED
    assert "131026" in log.why(m, NOW)


def test_a_send_the_platform_failed_is_not_sent(db):
    """What happened to today's documents messages on the server."""
    _message(db, job_id="a", kind=log.KIND_DOCUMENTS_READY)
    log.refresh(db, platform=FakePlatform(
        status={"a": _delivery("n/a", sent_status="failed")}), now=NOW)
    m = db.execute(select(WhatsAppMessage)).scalars().one()
    assert m.send_status == "failed" and log.stage(m, NOW) == log.NOT_SENT


def test_still_not_on_the_phone_after_a_day_is_not_received(db):
    m = _message(db, sent_at=NOW - timedelta(hours=30))
    assert log.stage(m, NOW) == log.NOT_RECEIVED
    m2 = _message(db, job_id="j2", sent_at=NOW - timedelta(hours=2))
    assert log.stage(m2, NOW) == log.SENT


def test_old_or_settled_messages_are_not_checked_again(db):
    _message(db, job_id="old", sent_at=NOW - timedelta(days=30))
    _message(db, job_id="read", delivery_status="read")
    _message(db, job_id="waiting", send_status=wa.PENDING)
    out = log.refresh(db, platform=FakePlatform(), now=NOW)
    assert out["checked"] == 0


def test_one_failed_check_is_kept_and_the_rest_carry_on(db):
    _message(db, job_id="a")
    out = log.refresh(db, platform=FakePlatform(
        fail={"get_delivery_status"}), now=NOW)
    m = db.execute(select(WhatsAppMessage)).scalars().one()
    assert "get_delivery_status is down" in m.check_error
    assert out["checked"] == 0


# ---- answers ---------------------------------------------------------------

def test_a_filled_in_form_is_the_answer(db):
    _csp(db)
    request = DataRequest(csp_id="1A850001", token_hash="h" * 64,
                          fields=["gender"], status=ANSWERED,
                          expires_at=NOW + timedelta(days=7),
                          answered_at=NOW - timedelta(minutes=5))
    db.add(request)
    db.commit()
    _message(db, data_request_id=request.id, delivery_status="read",
             response_kind="whatsapp", responded_at=NOW - timedelta(minutes=50),
             response_text="ok")
    log.refresh(db, platform=FakePlatform(), now=NOW)
    m = db.execute(select(WhatsAppMessage)).scalars().one()
    assert m.response_kind == "form"
    assert m.responded_at == NOW - timedelta(minutes=5)


def test_a_reply_answers_the_latest_message_to_that_number(db):
    first = _message(db, job_id="a", sent_at=NOW - timedelta(hours=5),
                     delivery_status="read")
    second = _message(db, job_id="b", kind=log.KIND_DOCUMENTS_READY,
                      sent_at=NOW - timedelta(hours=2), delivery_status="read")
    inbox = (
        '{"body": "Yes", "from_phone": "919812345670", "msg_type": "text",'
        ' "sent_at": "2026-10-15T09:00:00+00:00"}'
        '{"body": "someone else", "from_phone": "919999999999",'
        ' "msg_type": "text", "sent_at": "2026-10-15T09:10:00+00:00"}'
        '{"body": "before anything", "from_phone": "919812345670",'
        ' "msg_type": "text", "sent_at": "2026-10-15T01:00:00+00:00"}'
    )
    out = log.refresh(db, platform=FakePlatform(inbox=inbox), now=NOW)
    assert out["responded"] == 1
    db.refresh(first)
    db.refresh(second)
    assert first.responded_at is None
    assert second.response_kind == "whatsapp" and second.response_text == "Yes"


# ---- the platform's history -------------------------------------------------

def test_sends_missing_from_the_record_are_found_in_the_history(db):
    _csp(db, "1A852418")
    _message(db, job_id="known", csp_id="1A852418")
    history = (
        '{"job_id": "known", "sheet_name": "CSPdocMaker documents 1A852418",'
        ' "sent": 1, "failed": 0, "skipped": 0,'
        ' "timestamp": "2026-10-15T07:21:13+00:00"}'
        '{"job_id": "new1", "sheet_name": "CSPdocMaker documents 1A852418",'
        ' "sent": 0, "failed": 1, "skipped": 0, "template_name": "auto_x",'
        ' "timestamp": "2026-10-15T07:21:13+00:00"}'
        '{"job_id": "other", "sheet_name": "csp-agent-ONBOARD_ALL-1",'
        ' "sent": 1, "failed": 0, "skipped": 0,'
        ' "timestamp": "2026-10-15T07:21:13+00:00"}'
        '{"job_id": "elsewhere", "sheet_name": "CSPdocMaker documents 9Z0000",'
        ' "sent": 1, "failed": 0, "skipped": 0,'
        ' "timestamp": "2026-10-15T07:21:13+00:00"}'
    )
    out = log.refresh(db, platform=FakePlatform(history=history), now=NOW)
    assert out["imported"] == 1
    found = db.execute(select(WhatsAppMessage).where(
        WhatsAppMessage.job_id == "new1")).scalars().one()
    assert found.kind == log.KIND_DOCUMENTS_READY
    assert found.send_status == "failed" and found.source == "history"
    assert found.phone == "919812345670"
    # Another team's send, and a CSP this workspace does not hold, are not.
    assert db.execute(select(WhatsAppMessage).where(
        WhatsAppMessage.job_id.in_(["other", "elsewhere"]))).first() is None


def test_a_platform_outage_is_reported_and_the_rest_still_runs(db):
    _message(db, job_id="a")
    out = log.refresh(db, platform=FakePlatform(
        status={"a": _delivery("read")},
        fail={"get_send_history", "get_incoming_messages"}), now=NOW)
    assert len(out["errors"]) == 2
    assert any("send history" in e for e in out["errors"])
    assert any("WhatsApp replies" in e for e in out["errors"])
    assert out["checked"] == 1      # delivery was still checked


# ---- the counts ---------------------------------------------------------------

def test_the_counts_per_message(db):
    _message(db, job_id="a", delivery_status="read",
             responded_at=NOW, response_kind="form")
    _message(db, job_id="b", delivery_status="delivered")
    _message(db, job_id="c", send_status=wa.REJECTED)
    _message(db, job_id="d", kind=log.KIND_DOCUMENTS_READY,
             delivery_status="failed")
    rows = db.execute(select(WhatsAppMessage)).scalars().all()
    counts = log.summarise(rows, NOW)
    ask = counts[log.KIND_DATA_REQUEST]
    assert ask["total"] == 3
    assert (ask["read"], ask["delivered"], ask["not_sent"]) == (1, 1, 1)
    # A message that never left is neither answered nor unanswered.
    assert (ask["responded"], ask["not_responded"]) == (1, 1)
    assert counts[log.KIND_DOCUMENTS_READY]["not_received"] == 1
    assert counts[log.KIND_MISSING_DATA]["total"] == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_the_screen_gets_counts_and_rows(client, db):
    from tests.test_role_separation import _auth
    _message(db, job_id="a", delivery_status="read",
             sent_at=datetime.now(timezone.utc) - timedelta(hours=1))
    _message(db, job_id="t", is_test=True,
             sent_at=datetime.now(timezone.utc) - timedelta(hours=1))
    r = await client.get("/api/admin/whatsapp-messages", headers=_auth("admin"))
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["data_request"]["total"] == 2
    assert {row["job_id"] for row in body["rows"]} == {"a", "t"}

    r = await client.get("/api/admin/whatsapp-messages?include_tests=false",
                         headers=_auth("super_admin"))
    assert [row["job_id"] for row in r.json()["rows"]] == ["a"]

    r = await client.get("/api/admin/whatsapp-messages?kind=nonsense",
                         headers=_auth("admin"))
    assert r.status_code == 400


# ---- one message opened: what the CSP changed (No. 111) ----------------------

def test_each_field_says_what_the_csp_did_with_it():
    from types import SimpleNamespace
    request = SimpleNamespace(
        status=ANSWERED, answered_at=NOW, expires_at=NOW,
        fields=["gender", "ao", "email", "mobile", "photo_url"],
        previous_values={"gender": "Male", "ao": "", "email": "a@b.in",
                         "mobile": "9812345670"},
        answered_values={"gender": "Female", "ao": "Panchkula",
                         "email": " A@B.in "},
        photo_sent_at=None, sheet_saved=["ao", "gender"], sheet_error=None)
    out = log.changes(request)
    outcomes = {f["field"]: f["outcome"] for f in out["fields"]}
    assert outcomes == {"gender": "changed", "ao": "added",
                        "email": "confirmed", "mobile": "blank"}
    gender = next(f for f in out["fields"] if f["field"] == "gender")
    assert (gender["before"], gender["after"]) == ("Male", "Female")
    assert out["photo_asked"] is True and out["before_known"] is True
    assert out["counts"]["changed"] == 1


def test_an_older_answer_does_not_guess_what_was_there_before():
    from types import SimpleNamespace
    request = SimpleNamespace(
        status=ANSWERED, answered_at=NOW, expires_at=NOW, fields=["gender"],
        previous_values=None, answered_values={"gender": "Female"},
        photo_sent_at=None, sheet_saved=None, sheet_error=None)
    out = log.changes(request)
    assert out["before_known"] is False
    assert out["fields"][0]["before"] is None
    assert out["fields"][0]["outcome"] == "given"


@pytest.mark.asyncio(loop_scope="session")
async def test_the_form_keeps_what_was_there_and_the_message_shows_it(
        client, db, monkeypatch):
    from app.services import data_request_service as drs
    from app.services import sheet_writeback_service as wb
    from tests.test_role_separation import _auth

    db.add(CSPRecord(csp_id="1A910008", csp_code="1A910008", name="Form Csp",
                     gender="Male", ao="", mobile="9812345670"))
    db.flush()
    request, token = drs.create(db, "1A910008", ["gender", "ao", "mobile"])
    db.commit()
    message = _message(db, csp_id="1A910008", data_request_id=request.id,
                       delivery_status="read",
                       sent_at=datetime.now(timezone.utc) - timedelta(hours=1))
    monkeypatch.setattr(wb, "write_values",
                        lambda code, values, **k: (dict(values), []))

    r = await client.post(f"/api/csp-form/{token}",
                          json={"values": {"gender": "Female", "ao": "Panchkula",
                                           "mobile": "9812345670"}})
    assert r.status_code == 200, r.text
    db.expire_all()
    saved = db.get(DataRequest, request.id)
    assert saved.previous_values == {"gender": "Male", "ao": "",
                                     "mobile": "9812345670"}
    assert saved.sheet_saved == ["ao", "gender", "mobile"]

    r = await client.get(f"/api/admin/whatsapp-messages/{message.id}",
                         headers=_auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    outcomes = {f["field"]: f["outcome"] for f in body["request"]["fields"]}
    assert outcomes == {"gender": "changed", "ao": "added",
                        "mobile": "confirmed"}

    # An RM may not open it; an unknown message is a plain 404.
    r = await client.get(f"/api/admin/whatsapp-messages/{message.id}",
                         headers=_auth("rm"))
    assert r.status_code == 403
    r = await client.get("/api/admin/whatsapp-messages/"
                         "00000000-0000-4000-8000-0000000000ff",
                         headers=_auth("admin"))
    assert r.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_a_sheet_failure_is_kept_and_the_csp_still_succeeds(
        client, db, monkeypatch):
    from app.services import data_request_service as drs
    from app.services import sheet_writeback_service as wb

    db.add(CSPRecord(csp_id="1A910009", csp_code="1A910009", name="Sheet Down",
                     gender="Male"))
    db.flush()
    request, token = drs.create(db, "1A910009", ["gender"])
    db.commit()

    def down(code, values, **k):
        raise wb.SheetWriteError("Google Sheets unreachable")
    monkeypatch.setattr(wb, "write_values", down)

    r = await client.post(f"/api/csp-form/{token}",
                          json={"values": {"gender": "Female"}})
    assert r.status_code == 200 and r.json()["sheet_pending"] is True
    db.expire_all()
    saved = db.get(DataRequest, request.id)
    assert "unreachable" in saved.sheet_error
    assert log.changes(saved)["fields"][0]["outcome"] == "changed"


# ---- automatic greetings are not answers (No. 112) ---------------------------

GREETING = ("🌟🙏 कृष्णा CSC सैंटर में आपका हार्दिक स्वागत है। Online Services "
            "के लिए हमसे संपर्क करें।")


def _inbox(*replies):
    return "".join(
        '{"body": %s, "from_phone": "919812345670", "msg_type": "text", '
        '"sent_at": "%s"}' % (__import__("json").dumps(body), at)
        for at, body in replies)


def test_a_greeting_seconds_after_the_message_is_not_an_answer(db):
    """What 1A852418's shop sent back on 15 Oct, 5 seconds after."""
    m = _message(db, sent_at=datetime(2026, 10, 15, 7, 11, 48,
                                      tzinfo=timezone.utc))
    out = log.refresh(db, platform=FakePlatform(
        inbox=_inbox(("2026-10-15T07:11:53+00:00", GREETING))), now=NOW)
    db.refresh(m)
    assert out["responded"] == 0
    assert m.responded_at is None and m.response_kind is None
    assert m.auto_reply_text.startswith("🌟")
    assert log.as_row(m, NOW)["responded"] is False


def test_a_greeting_noted_before_our_send_was_recorded_is_still_automatic(db):
    """sent_at is noted when the platform answers — a few seconds late."""
    m = _message(db, sent_at=datetime(2026, 10, 15, 7, 11, 56,
                                      tzinfo=timezone.utc))
    log.refresh(db, platform=FakePlatform(
        inbox=_inbox(("2026-10-15T07:11:53+00:00", GREETING))), now=NOW)
    db.refresh(m)
    assert m.responded_at is None and m.auto_reply_at is not None


def test_a_real_reply_after_the_greeting_is_the_answer(db):
    m = _message(db, sent_at=datetime(2026, 10, 15, 7, 11, 48,
                                      tzinfo=timezone.utc))
    log.refresh(db, platform=FakePlatform(inbox=_inbox(
        ("2026-10-15T07:11:53+00:00", GREETING),
        ("2026-10-15T08:30:00+00:00", "Ji, form bhar diya"))), now=NOW)
    db.refresh(m)
    assert m.response_kind == "whatsapp"
    assert m.response_text == "Ji, form bhar diya"
    assert m.auto_reply_text.startswith("🌟")


def test_a_greeting_counted_before_this_fix_is_put_right(db):
    m = _message(db, sent_at=datetime(2026, 10, 15, 7, 11, 48,
                                      tzinfo=timezone.utc),
                 responded_at=datetime(2026, 10, 15, 7, 11, 53,
                                       tzinfo=timezone.utc),
                 response_kind="whatsapp", response_text=GREETING)
    log.refresh(db, platform=FakePlatform(), now=NOW)
    db.refresh(m)
    assert m.responded_at is None and m.response_kind is None
    assert m.auto_reply_text == GREETING


def test_the_chat_is_in_order_with_the_greeting_marked(db):
    ours = [_message(db, sent_at=datetime(2026, 10, 15, 7, 11, 48,
                                          tzinfo=timezone.utc))]
    replies = [
        {"sent_at": "2026-10-15T08:30:00+00:00", "body": "Ji",
         "msg_type": "text"},
        {"sent_at": "2026-10-15T07:11:53+00:00", "body": GREETING,
         "msg_type": "text"},
        {"sent_at": "2026-10-10T08:00:00+00:00", "body": "days before",
         "msg_type": "text"},
    ]
    chat = log.build_conversation(ours, replies, ours[0].sent_at)
    assert [(c["from"], c["automatic"]) for c in chat] == [
        ("us", False), ("csp", True), ("csp", False)]
    assert chat[0]["text"] == "Data verification message"


@pytest.mark.asyncio(loop_scope="session")
async def test_the_chat_comes_from_the_platform_or_says_why_not(
        client, db, monkeypatch):
    from tests.test_role_separation import _auth
    m = _message(db, sent_at=datetime.now(timezone.utc) - timedelta(hours=1))
    reply_at = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    asked = {}

    def tool(name, arguments):
        asked.update(name=name, arguments=arguments)
        return {"text": '{"body": "ok ji", "from_phone": "919812345670", '
                        '"msg_type": "text", "sent_at": "%s"}'
                        '{"body": "not them", "from_phone": "919999999999", '
                        '"msg_type": "text", "sent_at": "%s"}'
                        % (reply_at, reply_at)}
    monkeypatch.setattr(wa, "call_tool", tool)
    r = await client.get(f"/api/admin/whatsapp-messages/{m.id}/conversation",
                         headers=_auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert asked == {"name": "get_incoming_messages",
                     "arguments": {"phone": "919812345670"}}
    assert [c["text"] for c in body["items"] if c["from"] == "csp"] == ["ok ji"]
    assert body["error"] is None

    def down(name, arguments):
        raise wa.WhatsAppPlatformError("platform unreachable")
    monkeypatch.setattr(wa, "call_tool", down)
    r = await client.get(f"/api/admin/whatsapp-messages/{m.id}/conversation",
                         headers=_auth("admin"))
    assert r.status_code == 200
    assert "platform unreachable" in r.json()["error"]

    r = await client.get(f"/api/admin/whatsapp-messages/{m.id}/conversation",
                         headers=_auth("rm"))
    assert r.status_code == 403
