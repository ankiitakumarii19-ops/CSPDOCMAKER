"""A WhatsApp that failed is sent again until it goes (No. 164).

Every send error is tried again — with longer waits — except a number that
is not on WhatsApp (the contact loop's) and a wording Meta refused.
Sending is a stand-in: nothing leaves the test.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.models.data_request import DataRequest
from app.models.feedback_loop import ContactFix, CspFeedback
from app.models.whatsapp_message import WhatsAppMessage
from app.services import csp_replies as cr
from app.services import documents_feedback as dfb
from app.services import feedback_loops as fl
from app.services import resend_failed as rf
from app.services import send_reason
from tests.test_csp_replies import FakeWhatsApp, rdb  # noqa: F401
from tests.test_feedback_loops import _csp, ldb, senders  # noqa: F401
from tests.test_field_quality import _engine, qdb  # noqa: F401

# Messages are dated from NOW and the runs are given now=NOW: a long test
# run must not move the clock under the waits. (Replies and the feedback
# question are dated by the database, so they use the real clock.)
NOW = datetime.now(timezone.utc)
CODE = "1A996001"
PLATFORM_DOWN = ("WhatsApp platform unreachable: ConnectError: [Errno -3] "
                 "Temporary failure in name resolution")
SETTINGS = SimpleNamespace(resend_failed_batch=20, verify_old_csps_enabled=False,
                           calling_sheet_id="")


def _failed(db, minutes_ago=40, kind="data_request", error=PLATFORM_DOWN,
            status="failed", code=CODE, because=None):
    m = WhatsAppMessage(csp_id=code, phone="919812345601", kind=kind, source="t",
                        send_status=status, send_error=error,
                        sent_because=because,
                        sent_at=NOW - timedelta(minutes=minutes_ago))
    db.add(m)
    db.commit()
    return m


@pytest.fixture
def why(monkeypatch, senders):
    """The send reason in force at each ask."""
    from app.services import message_sender
    seen, ask = [], message_sender.ask_for_details

    def capture(session, record, **kw):
        seen.append(send_reason.current())
        return ask(session, record, **kw)
    monkeypatch.setattr(message_sender, "ask_for_details", capture)
    return seen


def test_the_waits_grow_to_every_4_hours():
    assert [rf.wait(n) for n in (1, 2, 3, 4, 5, 9)] == [
        timedelta(minutes=30), timedelta(hours=1), timedelta(hours=2),
        timedelta(hours=4), timedelta(hours=4), timedelta(hours=4)]


@pytest.mark.parametrize("reason,mine", [
    (PLATFORM_DOWN, False),
    ("smart_send_template failed: Could not reach Meta API", False),
    ("not a usable mobile number: '98123'", True),
    ("(#131026) Message undeliverable", True),
    ("Recipient is not a valid WhatsApp user", True),
])
def test_a_number_not_on_whatsapp_is_told_apart(reason, mine):
    assert rf.not_on_whatsapp(reason) is mine


def test_a_platform_error_is_sent_again(ldb, senders, why):
    _csp(ldb)
    m = _failed(ldb)
    assert rf.run(ldb, SETTINGS, now=NOW)["sent"] == 1
    assert senders["ask"] == [(CODE, "whatsapp", None, True)]
    assert why == [send_reason.RETRY], "says 'sent again after an error'"
    ldb.expire_all()
    assert (m.retry_note, m.retry_status) == ("sent", None)


def test_not_before_the_wait(ldb, senders):
    _csp(ldb)
    _failed(ldb, minutes_ago=10)
    assert rf.run(ldb, SETTINGS, now=NOW)["sent"] == 0
    assert senders["ask"] == []


def test_the_second_failure_waits_an_hour(ldb, senders):
    _csp(ldb)
    _failed(ldb, minutes_ago=120)
    _failed(ldb, minutes_ago=45)                    # the first try again failed
    assert rf.run(ldb, SETTINGS, now=NOW)["sent"] == 0
    assert rf.run(ldb, SETTINGS, now=NOW + timedelta(minutes=20))["sent"] == 1


def test_meta_waiting_for_approval_is_tried_again(ldb, senders):
    _csp(ldb)
    _failed(ldb, status="pending", error="waiting for Meta to approve")
    assert rf.run(ldb, SETTINGS, now=NOW)["sent"] == 1


@pytest.mark.parametrize("status,error", [
    ("failed", "(#131026) Message undeliverable"),      # contact loop's
    ("rejected", "Meta rejected the wording: bad"),     # a person's
    ("sent", None),                                     # it went
])
def test_what_is_not_sent_again(ldb, senders, status, error):
    _csp(ldb)
    _failed(ldb, status=status, error=error)
    rf.run(ldb, SETTINGS, now=NOW)
    assert senders["ask"] == []


def test_a_later_send_that_went_ends_it(ldb, senders):
    _csp(ldb)
    _failed(ldb, minutes_ago=90)
    _failed(ldb, minutes_ago=60, status="sent", error=None)
    rf.run(ldb, SETTINGS, now=NOW)
    assert senders["ask"] == []


def test_a_number_not_on_whatsapp_goes_to_the_contact_loop(ldb, senders):
    _csp(ldb)
    _failed(ldb, error="Recipient is not a valid WhatsApp user")
    assert fl.find_problems(ldb) == 1
    ldb.commit()
    fix = ldb.execute(select(ContactFix)).scalar_one()
    assert (fix.problem, fix.bad_value) == ("whatsapp_undelivered", "919812345601")


def test_left_to_the_job_that_sent_it(ldb, senders):
    _csp(ldb, origin="new")                     # the new-CSP job tries again
    _failed(ldb)
    rf.run(ldb, SETTINGS, now=NOW)
    assert senders["ask"] == []


def test_left_to_the_contact_loop_while_it_works_on_the_csp(ldb, senders):
    _csp(ldb)
    ldb.add(ContactFix(csp_id=CODE, problem="email_bounced", bad_value="x",
                       status="asked"))
    _failed(ldb)
    rf.run(ldb, SETTINGS, now=NOW)
    assert senders["ask"] == []


def test_not_needed_once_they_filled_in_the_form(ldb, senders):
    _csp(ldb)
    m = _failed(ldb, minutes_ago=60)
    ldb.add(DataRequest(csp_id=CODE, token_hash="h" * 64, fields=["name"],
                        status="answered", expires_at=NOW + timedelta(days=7),
                        answered_at=NOW - timedelta(minutes=30)))
    ldb.commit()
    assert rf.run(ldb, SETTINGS, now=NOW)["not_needed"] == 1
    ldb.expire_all()
    assert m.retry_status == "not_needed"
    rf.run(ldb, SETTINGS, now=NOW + timedelta(days=1))
    assert senders["ask"] == [], "never tried again"


def test_a_decided_not_send_stops_but_a_waiting_one_does_not(ldb, senders):
    _csp(ldb)
    m = _failed(ldb, minutes_ago=60)
    senders["ask_result"] = {"sent": False,
                             "reason": "the last try failed; tried again 30 minutes after it"}
    assert rf.run(ldb, SETTINGS, now=NOW)["waiting"] == 1
    ldb.expire_all()
    assert m.retry_status is None and m.retried_at is not None
    senders["ask_result"] = {"sent": False,
                             "reason": "already asked and waiting for a reply"}
    assert rf.run(ldb, SETTINGS, now=NOW + timedelta(hours=1))["not_needed"] == 1


def test_documents_ready_is_sent_again(ldb, senders, monkeypatch):
    _csp(ldb)
    _failed(ldb, kind="documents_ready")
    calls = []
    monkeypatch.setattr(fl, "_resend_documents_whatsapp", lambda s, f, r, mobile=None: (
        calls.append((r.csp_id, mobile, send_reason.current()))
        or (True, "documents WhatsApp sent again", True)))
    assert rf.run(ldb, SETTINGS, now=NOW)["sent"] == 1
    assert calls == [(CODE, None, send_reason.RETRY)]


def test_the_alternate_number_is_kept(ldb, senders):
    _csp(ldb)
    _failed(ldb, because=send_reason.ALTERNATE_NUMBER)
    from app.services import message_sender
    seen = []
    ask = message_sender.ask_for_details
    message_sender.ask_for_details = lambda s, r, **kw: (
        seen.append(kw.get("mobile")) or ask(s, r, **kw))
    try:
        rf.run(ldb, SETTINGS, now=NOW)
    finally:
        message_sender.ask_for_details = ask
    assert seen == ["919812345601"]


def test_at_most_a_batch_a_run(ldb, senders):
    for i in range(3):
        code = f"1A99610{i}"
        _csp(ldb, code=code, csp_code=code)
        _failed(ldb, code=code)
    assert rf.run(ldb, SimpleNamespace(**{**vars(SETTINGS),
                                          "resend_failed_batch": 2}), now=NOW)["sent"] == 2


def test_a_failed_reply_is_sent_again(rdb):
    from tests.test_csp_replies import _csp as reply_csp
    reply_csp(rdb)
    reply = cr.CspReply(csp_id="1A997001", phone="919812345611", messages=[],
                        last_in_at=NOW - timedelta(hours=2), intents=["else"],
                        reply_text="Apne RM se baat karein.",
                        draft_text="Apne RM se baat karein.", status="failed",
                        decided_by="admin@eko.co.in", note=f"not sent: {PLATFORM_DOWN}")
    rdb.add(reply)
    rdb.commit()
    rdb.execute(text("UPDATE csp_replies SET updated_at = now() - interval '40 minutes'"))
    rdb.commit()
    wa = FakeWhatsApp()
    assert rf.run(rdb, SETTINGS, wa=wa)["sent"] == 1
    assert wa.sent == [("919812345611", "Apne RM se baat karein.")]
    rdb.expire_all()
    assert reply.status == "sent"
    sent = rdb.execute(select(WhatsAppMessage).where(
        WhatsAppMessage.kind == "other")).scalar_one()
    assert sent.sent_because == send_reason.RETRY


def test_a_reply_not_sent_yet_by_a_person_is_left_alone(rdb):
    from tests.test_csp_replies import _csp as reply_csp
    reply_csp(rdb)
    rdb.add(cr.CspReply(csp_id="1A997001", phone="919812345611", messages=[],
                        last_in_at=NOW - timedelta(hours=2), intents=["else"],
                        reply_text="x", status="draft"))
    rdb.commit()
    wa = FakeWhatsApp()
    rf.run(rdb, SETTINGS, wa=wa)
    assert wa.sent == []


# ---- the feedback question ----------------------------------------------

def _documents_message(db):
    db.add(WhatsAppMessage(csp_id="1A997001", phone="919812345611",
                           kind="documents_ready", source="t", send_status="sent",
                           delivery_status="read",
                           sent_at=NOW - timedelta(hours=3)))
    db.commit()


def test_the_feedback_question_is_tried_until_it_goes(rdb):
    from tests.test_csp_replies import _csp as reply_csp
    reply_csp(rdb)
    _documents_message(rdb)
    for _ in range(4):                          # more than the old 3 tries
        dfb.run(rdb, wa=FakeWhatsApp(result="failed"))
        rdb.execute(text("UPDATE csp_feedback SET updated_at = now() - interval '5 hours'"))
        rdb.commit()
    q = rdb.execute(select(CspFeedback)).scalar_one()
    assert (q.ask_status, q.tries) == ("pending", 4)
    assert dfb.run(rdb, wa=FakeWhatsApp())["asked"] == 1
    later = rdb.execute(select(WhatsAppMessage).where(
        WhatsAppMessage.kind == "feedback").order_by(WhatsAppMessage.sent_at.desc())
        ).scalars().first()
    assert later.sent_because == send_reason.RETRY


def test_the_feedback_question_waits_between_tries(rdb):
    from tests.test_csp_replies import _csp as reply_csp
    reply_csp(rdb)
    _documents_message(rdb)
    dfb.run(rdb, wa=FakeWhatsApp(result="failed"))
    wa = FakeWhatsApp()
    dfb.run(rdb, wa=wa)
    assert wa.sent == [], "not again straight away"


def test_the_feedback_question_stops_for_a_number_not_on_whatsapp(rdb):
    from tests.test_csp_replies import _csp as reply_csp

    class NotOnWhatsApp(FakeWhatsApp):
        def send(self, phone, body, values, source_name=None):
            super().send(phone, body, values, source_name)
            return {"status": "failed", "reason": "(#131026) Message undeliverable",
                    "job_id": None, "template_name": "t"}
    reply_csp(rdb)
    _documents_message(rdb)
    dfb.run(rdb, wa=NotOnWhatsApp())
    assert rdb.execute(select(CspFeedback.ask_status)).scalar_one() == "failed"
