"""Alternate number before email, and "did you get your documents?" (No. 152).

A WhatsApp that did not reach the phone is tried on the CSP's alternate
number; if that one works it replaces the old number in CSPDATA; with none
(or none that works) the CSP is emailed the data verification form. The day
after the documents the CSP is asked 1 / 2 / 3, and the answer is acted on
when the reply is sent. Every send is a stand-in.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.models.feedback_loop import ContactFix, CspFeedback
from app.models.whatsapp_message import WhatsAppMessage
from app.services import csp_replies as cr
from app.services import documents_feedback as dfb
from app.services import feedback_loops as fl
from tests.test_csp_replies import FakeWhatsApp, _in, rdb  # noqa: F401
from tests.test_feedback_loops import (SETTINGS, _csp, _fix, ldb,  # noqa: F401
                                       senders)
from tests.test_field_quality import _auth, _engine, qdb  # noqa: F401

on_loop = pytest.mark.asyncio(loop_scope="session")

NOW = datetime.now(timezone.utc)
MAIN, ALT = "919812345601", "919812345602"


def _wa(db, phone=MAIN, delivery="failed", kind="data_request", hours_ago=2,
        code="1A996001", at=None):
    m = WhatsAppMessage(csp_id=code, phone=phone, kind=kind, source="t",
                        send_status="sent", delivery_status=delivery,
                        sent_at=at or NOW - timedelta(hours=hours_ago))
    db.add(m)
    db.commit()
    return m


@pytest.fixture
def sheet(monkeypatch):
    from app.services import sheet_writeback_service as wb
    writes = []
    monkeypatch.setattr(wb, "write_values", lambda code, values, *a, **k: (
        writes.append((code, dict(values))) or (dict(values), [])))
    return writes


# ---- the alternate number -----------------------------------------------

def test_the_second_number_in_the_cell_is_tried_first(ldb, senders,
                                                      monkeypatch):
    _csp(ldb, mobile="9812345601/ 9812345602")
    _wa(ldb)
    asked = []
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "ask_for_details", lambda s, r, **kw: (
        asked.append(kw) or {"sent": True, "via": "whatsapp"}))
    fl.run(ldb, SETTINGS)
    (kw,) = asked
    assert (kw["mobile"], kw["channel"].kind, kw["verify"]) == (ALT, "whatsapp", True)
    fix = _fix(ldb)
    assert (fix.status, fix.alternate, fix.alternates_tried) == (
        "trying_alternate", ALT, [ALT])


def test_a_working_alternate_replaces_the_number_in_cspdata(ldb, senders, sheet):
    _csp(ldb, mobile="9812345601/ 9812345602")
    _wa(ldb)
    fl.run(ldb, SETTINGS)
    _wa(ldb, phone=ALT, delivery="delivered", at=NOW + timedelta(minutes=1))
    fl.run(ldb, SETTINGS, now=NOW + timedelta(minutes=10))
    assert sheet == [("1A996001", {"mobile": "9812345602"})]
    fix = _fix(ldb)
    assert (fix.status, fix.corrected_value) == ("done", ALT)
    assert "CSPDATA updated" in fix.note
    ldb.expire_all()
    from app.models.csp_record import CSPRecord
    assert ldb.execute(select(CSPRecord.mobile)).scalar_one() == "9812345602"


def test_an_unreachable_alternate_falls_back_to_email(ldb, senders, sheet):
    _csp(ldb, mobile="9812345601/ 9812345602")
    _wa(ldb)
    fl.run(ldb, SETTINGS)
    _wa(ldb, phone=ALT, delivery="failed", at=NOW + timedelta(minutes=1))
    fl.run(ldb, SETTINGS, now=NOW + timedelta(minutes=10))
    assert senders["ask"][-1][1:] == ("email", True, True), "emailed the form"
    assert sheet == []
    fixes = ldb.execute(select(ContactFix)).scalars().all()
    assert len(fixes) == 1, "the alternate's failure is not a problem of its own"
    assert fixes[0].status == "asked" and fixes[0].asked_via == "email"


def test_no_alternate_means_email_straight_away(ldb, senders):
    _csp(ldb)
    _wa(ldb)
    fl.run(ldb, SETTINGS)
    assert senders["ask"] == [("1A996001", "email", True, True)]


def test_the_zoho_alternate_is_used_when_the_cell_has_one_number(
        ldb, senders, monkeypatch):
    _csp(ldb)
    _wa(ldb)
    monkeypatch.setattr(fl, "_zoho_numbers", lambda s, r: [MAIN, ALT])
    fl.run(ldb, SETTINGS)
    assert _fix(ldb).alternate == ALT


def test_a_documents_message_goes_to_the_alternate(ldb, senders,
                                                   monkeypatch):
    from app.models.processing_job import ProcessingJob
    _csp(ldb, mobile="9812345601/ 9812345602")
    ldb.add(ProcessingJob(job_id="job-alt-1", csp_id="1A996001",
                          workflow_type="new_csp"))
    ldb.commit()
    _wa(ldb, kind="documents_ready")
    from app.services import documents_whatsapp
    sent = []
    monkeypatch.setattr(documents_whatsapp, "notify",
                        lambda s, csp, job, names, mobile=None: (
                            sent.append(mobile) or {"status": "sent"}))
    fl.run(ldb, SETTINGS)
    assert sent == [ALT]


def test_no_delivery_after_a_day_counts_as_unreachable(ldb, senders):
    _csp(ldb)
    _wa(ldb, delivery="sent", hours_ago=30)
    assert fl.run(ldb, SETTINGS)["found"] == 1


# ---- the feedback question ----------------------------------------------

@pytest.mark.parametrize("reply,answer", [
    ("1", "1"), ("2", "2"), ("3 ", "3"), ("1 mil gaye", "1"),
    ("haan mil gaye sab sahi hai", "1"), ("nahi mile", "2"),
    ("abhi tak nahi mila", "2"), ("naam galat hai", "3"),
    ("hello", None), ("12345", None),
])
def test_answers_are_read(reply, answer):
    assert dfb.parse_answer(reply) == answer


@pytest.fixture
def fdb(rdb):
    rdb.execute(text("TRUNCATE csp_feedback, contact_fixes RESTART IDENTITY CASCADE"))
    rdb.commit()
    return rdb


def _documents_message(db, hours_ago=30, delivery="read", code="1A997001"):
    from tests.test_csp_replies import PHONE
    return _wa(db, phone=PHONE, delivery=delivery, kind="documents_ready",
               hours_ago=hours_ago, code=code)


def test_the_question_goes_15_minutes_after_the_documents_once(fdb):
    from tests.test_csp_replies import _csp as reply_csp
    reply_csp(fdb)
    _documents_message(fdb, hours_ago=20 / 60)       # 20 minutes ago
    wa = FakeWhatsApp()
    assert dfb.run(fdb, wa=wa)["asked"] == 1
    assert "Reply karein: 1" in dfb.WORDING
    assert dfb.run(fdb, wa=wa)["asked"] == 0, "once"
    row = fdb.execute(select(CspFeedback)).scalar_one()
    assert (row.ask_status, row.answer) == ("sent", None)
    assert fdb.execute(select(WhatsAppMessage).where(
        WhatsAppMessage.kind == "feedback")).scalars().first() is not None


@pytest.mark.parametrize("hours_ago,delivery,hold", [
    (10 / 60, "read", None),           # only 10 minutes yet
    (24 * 8, "read", None),            # too late
    (30, "failed", None),              # never reached the phone
    (30, "read", "Not live yet"),      # on hold
])
def test_the_question_is_not_sent_when_it_should_not_be(fdb, hours_ago,
                                                        delivery, hold):
    from tests.test_csp_replies import _csp as reply_csp
    reply_csp(fdb, send_hold=hold)
    _documents_message(fdb, hours_ago=hours_ago, delivery=delivery)
    assert dfb.run(fdb, wa=FakeWhatsApp())["asked"] == 0


def test_a_wording_waiting_for_meta_is_tried_again(fdb):
    from tests.test_csp_replies import _csp as reply_csp
    reply_csp(fdb)
    _documents_message(fdb)
    assert dfb.run(fdb, wa=FakeWhatsApp(result="pending"))["pending"] == 1
    assert dfb.run(fdb, wa=FakeWhatsApp())["asked"] == 1


def _asked(db):
    from tests.test_csp_replies import _csp as reply_csp, _ours
    reply_csp(db)
    _ours(db)
    _documents_message(db)
    dfb.run(db, wa=FakeWhatsApp())
    q = db.execute(select(CspFeedback)).scalar_one()
    q.asked_at = NOW - timedelta(hours=1)
    db.commit()
    return q


def test_answer_2_resends_the_documents_and_the_link_when_the_reply_is_sent(
        fdb, monkeypatch):
    """No. 163: answer 2 also gets the data verification link (to correct
    the email)."""
    from app.services import message_sender
    _asked(fdb)
    cr.collect(fdb, FakeWhatsApp([_in("2", 30)]))
    fdb.commit()
    q = fdb.execute(select(CspFeedback)).scalar_one()
    assert (q.answer, q.answer_text) == ("2", "2")
    reply = fdb.execute(select(cr.CspReply)).scalar_one()
    assert (reply.intents, reply.action) == (["feedback_2"],
                                             "resend_documents,fresh_link")
    assert "dobara reply@example.com par" in reply.reply_text
    assert "data verification ka link" in reply.reply_text
    resent, asked = [], []
    monkeypatch.setattr(fl, "resend_documents_email", lambda s, r: (
        resent.append(r.email) or (True, "documents emailed again", True)))
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: asked.append(kw) or {"sent": True})
    cr.send(fdb, reply, "admin@eko.co.in", wa=FakeWhatsApp())
    assert resent == ["reply@example.com"]
    assert asked == [{"verify": True, "manual": True}]
    assert "documents emailed again" in reply.note and "new link sent" in reply.note


def test_answer_3_sends_the_data_verification_message(fdb, monkeypatch):
    from app.services import message_sender
    _asked(fdb)
    cr.collect(fdb, FakeWhatsApp([_in("3 naam galat hai", 30)]))
    fdb.commit()
    reply = fdb.execute(select(cr.CspReply)).scalar_one()
    assert reply.intents[0] == "feedback_3" and reply.action == "fresh_link"
    asked = []
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: asked.append(kw) or {"sent": True})
    cr.send(fdb, reply, "admin@eko.co.in", wa=FakeWhatsApp())
    assert asked == [{"verify": True, "manual": True}]


def test_answer_1_is_thanked_and_nothing_else_happens(fdb):
    _asked(fdb)
    cr.collect(fdb, FakeWhatsApp([_in("1", 30)]))
    fdb.commit()
    reply = fdb.execute(select(cr.CspReply)).scalar_one()
    assert (reply.intents, reply.action) == (["feedback_1"], None)
    assert reply.reply_text.startswith("Dhanyavaad!")


def test_a_quick_answer_is_not_mistaken_for_an_automatic_greeting(fdb):
    q = _asked(fdb)
    fdb.execute(text("UPDATE whatsapp_messages SET sent_at = :t WHERE kind = 'feedback'"),
                {"t": q.asked_at})
    fdb.commit()
    quick = {"from_phone": "919812345611", "body": "1", "msg_type": "text",
             "sent_at": (q.asked_at + timedelta(seconds=20)).isoformat()}
    cr.collect(fdb, FakeWhatsApp([quick]))
    fdb.commit()
    assert fdb.execute(select(CspFeedback.answer)).scalar_one() == "1"


def test_asking_to_change_details_sends_the_data_verification_message(
        fdb, monkeypatch):
    from app.services import message_sender
    from tests.test_csp_replies import _csp as reply_csp, _ours
    reply_csp(fdb, origin="new")
    _ours(fdb)
    cr.collect(fdb, FakeWhatsApp([_in("address change karna hai", 30)]))
    fdb.commit()
    reply = fdb.execute(select(cr.CspReply)).scalar_one()
    asked = []
    monkeypatch.setattr(message_sender, "ask_for_details",
                        lambda s, r, **kw: asked.append(kw) or {"sent": True})
    cr.send(fdb, reply, "admin@eko.co.in", wa=FakeWhatsApp())
    assert asked == [{"verify": True, "manual": True}], "even for a new CSP"


@on_loop
async def test_the_feedback_summary_is_for_admins(client, fdb):
    _asked(fdb)
    r = await client.get("/api/admin/quality/feedback", headers=_auth("rm"))
    assert r.status_code == 403
    r = await client.get("/api/admin/quality/feedback", headers=_auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["asked"], body["no_answer"]) == (1, 1)


# ---- the Calling sheet's alternate number (No. 157) ----------------------

@pytest.fixture
def calling(monkeypatch):
    from app.config import get_settings
    from app.services import source_sheets
    state = {"rows": [], "fail": False}
    monkeypatch.setattr(get_settings(), "calling_sheet_id", "calling-0001")

    def read(sheet, tab, header_row):
        if state["fail"]:
            raise RuntimeError("Google is down")
        return state["rows"]
    monkeypatch.setattr(source_sheets, "read_rows", read)
    return state


def _calling_row(code="1A996001", main="9812345601", alt="9812345603",
                 dc="9000000999"):
    return {"CSP ID": code, "CSP Name": "Csp", "CSP Mobile number": main,
            "Alternate Mobile No.": alt, "Mobile Number DC": dc,
            "Relationship Manager": "Rm"}


def test_the_calling_sheets_alternate_number_is_tried(ldb, senders, calling,
                                                      monkeypatch):
    calling["rows"] = [_calling_row()]
    asked = []
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "ask_for_details", lambda s, r, **kw: (
        asked.append(kw.get("mobile")) or {"sent": True, "via": "whatsapp"}))
    _csp(ldb)                               # one number in CSPDATA
    _wa(ldb)
    fl.run(ldb, SETTINGS)
    assert asked == ["919812345603"], "the Calling sheet's alternate, not the DC's"
    assert _fix(ldb).alternate == "919812345603"


def test_the_second_number_in_cspdata_comes_before_the_calling_sheet(
        ldb, senders, calling):
    calling["rows"] = [_calling_row()]
    _csp(ldb, mobile="9812345601/ 9812345602")
    _wa(ldb)
    fl.run(ldb, SETTINGS)
    assert _fix(ldb).alternate == ALT


def test_an_unreadable_calling_sheet_falls_back_to_email(ldb, senders, calling):
    calling["fail"] = True
    _csp(ldb)
    _wa(ldb)
    fl.run(ldb, SETTINGS)
    assert senders["ask"] == [("1A996001", "email", True, True)]


def test_only_the_csps_own_number_columns_are_used():
    heads = ["CSP ID", "CSP Mobile number", "Alternate Mobile No.",
             "WhatsApp Number", "Mobile Number DC", "Branch Contact No.",
             "RM Mobile", "ASM Contact", "Aadhaar Number", "Account Number",
             "Pin Code", "Other Contact"]
    assert fl.calling_phone_columns(heads) == [
        "CSP Mobile number", "Alternate Mobile No.", "WhatsApp Number",
        "Other Contact"]


# ---- the feedback card on the WhatsApp messages page (No. 160) ----------

@on_loop
async def test_the_whatsapp_page_counts_the_feedback_question(client, fdb):
    _asked(fdb)
    cr.collect(fdb, FakeWhatsApp([_in("2", 30)]))
    fdb.commit()
    r = await client.get("/api/admin/whatsapp-messages?days=0",
                         headers=_auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["feedback"]["total"] == 1
    assert body["feedback_answers"] == {
        "answers": {"1": 0, "2": 1, "3": 0}, "no_answer": 0}
