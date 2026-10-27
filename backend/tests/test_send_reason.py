"""Why each WhatsApp / email was sent (No. 156).

Every new sending path says why — bounce, CSP asked, alternate number,
WhatsApp unreachable, reply, documents not received, sent again after a
correction — and the WhatsApp and Emails pages count and filter by it.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.models.email_message import EmailMessage
from app.models.whatsapp_message import WhatsAppMessage
from app.services import csp_replies as cr
from app.services import email_log
from app.services import feedback_loops as fl
from app.services import message_log
from app.services import send_reason as sr
from tests.test_alternate_and_feedback import _wa, sheet  # noqa: F401
from tests.test_csp_replies import (FakeWhatsApp, _in, _ours, rdb)  # noqa: F401
from tests.test_csp_replies import _csp as reply_csp
from tests.test_feedback_loops import (SETTINGS, _bounce, _csp, ldb,  # noqa: F401
                                       senders)
from tests.test_field_quality import _auth, _engine, qdb  # noqa: F401

on_loop = pytest.mark.asyncio(loop_scope="session")


def test_a_message_recorded_inside_a_reason_carries_it(ldb):
    outcome = {"status": "sent", "reason": "", "job_id": None, "template_name": "t"}
    with sr.because(sr.EMAIL_BOUNCED):
        message_log.record(ldb, kind="data_request", mobile="9812345601",
                           outcome=outcome, csp_id="1A996001")
    message_log.record(ldb, kind="data_request", mobile="9812345601",
                       outcome={**outcome}, csp_id="1A996001")
    ldb.commit()
    reasons = [m.sent_because for m in ldb.execute(
        select(WhatsAppMessage).order_by(WhatsAppMessage.sent_at)).scalars()]
    assert reasons == ["email_bounced", None]
    assert sr.current() is None, "the reason ends with the block"


def test_an_email_recorded_inside_a_reason_carries_it(ldb):
    with sr.because(sr.WHATSAPP_UNREACHABLE):
        email_log.record(kind="details_request", to_email="x@example.com",
                         subject="s", ok=True, csp_id="1A996001")
    ldb.expire_all()
    row = ldb.execute(select(EmailMessage).where(
        EmailMessage.csp_id == "1A996001")).scalars().first()
    assert row.sent_because == "whatsapp_unreachable"
    assert sr.label(row.sent_because) == "WhatsApp did not reach them"
    assert sr.label(None) == "Usual flow"


def _capture(monkeypatch):
    """ask_for_details stand-in that notes the reason in force."""
    from app.services import message_sender
    seen = []
    monkeypatch.setattr(message_sender, "ask_for_details", lambda s, r, **kw: (
        seen.append(sr.current()) or {"sent": True, "via": getattr(kw.get("channel"), "kind", "whatsapp")}))
    return seen


def test_the_contact_loop_says_why(ldb, senders, monkeypatch):
    seen = _capture(monkeypatch)
    _csp(ldb)
    _bounce(ldb)                              # email bounced -> WhatsApp ask
    _wa(ldb, phone="919812345601")            # WhatsApp unreachable -> email
    fl.run(ldb, SETTINGS)
    assert sorted(seen) == ["email_bounced", "whatsapp_unreachable"]


def test_the_alternate_number_says_why(ldb, senders, monkeypatch):
    seen = _capture(monkeypatch)
    _csp(ldb, mobile="9812345601/ 9812345602")
    _wa(ldb, phone="919812345601")
    fl.run(ldb, SETTINGS)
    assert seen == ["alternate_number"]


def test_a_resend_after_a_correction_says_why(ldb, senders, monkeypatch):
    seen = []
    monkeypatch.setattr(fl, "resend_documents_email", lambda s, r: (
        seen.append(sr.current()) or (True, "documents emailed again", True)))
    _csp(ldb)
    _bounce(ldb)
    fl.run(ldb, SETTINGS)
    ldb.execute(text("UPDATE csp_records SET email = 'right@example.com'"))
    ldb.commit()
    fl.run(ldb, SETTINGS)
    assert seen == ["contact_corrected"]


def test_replies_say_why(rdb, monkeypatch):
    seen = _capture(monkeypatch)
    reply_csp(rdb)
    _ours(rdb)
    cr.collect(rdb, FakeWhatsApp([_in("link open nahi hota", 10)]))
    rdb.commit()
    reply = rdb.execute(select(cr.CspReply)).scalar_one()
    cr.send(rdb, reply, "admin@eko.co.in", wa=FakeWhatsApp())
    rdb.commit()
    assert seen == ["csp_asked"], "the new link: the CSP asked"
    sent = rdb.execute(select(WhatsAppMessage).where(
        WhatsAppMessage.kind == "other")).scalars().first()
    assert sent.sent_because == "reply"


@on_loop
async def test_the_pages_count_and_filter_by_reason(client, ldb):
    outcome = {"status": "sent", "reason": "", "job_id": None, "template_name": "t"}
    with sr.because(sr.ALTERNATE_NUMBER):
        message_log.record(ldb, kind="data_request", mobile="9812345601",
                           outcome=outcome, csp_id="1A996001")
    message_log.record(ldb, kind="data_request", mobile="9812345602",
                       outcome={**outcome}, csp_id="1A996002")
    ldb.commit()
    with sr.because(sr.NOT_RECEIVED):
        email_log.record(kind="documents", to_email="y@example.com", subject="s",
                         ok=True, csp_id="1A996001")

    r = await client.get("/api/admin/whatsapp-messages?days=0", headers=_auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent_because"] == [{"key": "alternate_number", "count": 1,
                                     "label": "Alternate number (main one unreachable)"}]
    tagged = [x for x in body["rows"] if x["sent_because"]]
    assert [x["csp_id"] for x in tagged] == ["1A996001"]

    r = await client.get("/api/admin/email-messages?because=documents_not_received",
                         headers=_auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [m["sent_because_label"] for m in body["messages"]] == [
        "CSP said the documents did not arrive"]
    assert body["sent_because"][0]["key"] == "documents_not_received"
