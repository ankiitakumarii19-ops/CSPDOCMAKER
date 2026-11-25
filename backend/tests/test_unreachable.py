"""Can't reach a CSP after trying everything (No. 231).

Main number, every alternate, email: when none of them reaches the CSP, the
loop stops sending to the bad number / address, lists the CSP for the
Admins with why, and starts again by itself once CSPDATA has a new number
or email. Every send is a stand-in.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.email_message import EmailMessage
from app.models.feedback_loop import ContactFix
from app.services import feedback_loops as fl
from tests.test_alternate_and_feedback import ALT, MAIN, _wa, sheet  # noqa: F401
from tests.test_feedback_loops import (SETTINGS, _csp, ldb,  # noqa: F401
                                       senders)
from tests.test_field_quality import _engine, qdb  # noqa: F401

NOW = datetime.now(timezone.utc)
CODE = "1A996001"


def _bounce(db, to="loop@example.com"):
    db.add(EmailMessage(csp_id=CODE, to_email=to, kind="details_request",
                        subject="s", track_token=f"t-{to}", send_status="sent",
                        sent_at=NOW - timedelta(hours=3),
                        bounced_at=NOW - timedelta(hours=2)))
    db.commit()


def _fixes(db):
    db.expire_all()
    return {f.problem: f for f in db.execute(select(ContactFix)).scalars()}


def test_no_alternate_and_no_email_is_reported_with_why(ldb, senders):
    _csp(ldb, email="")
    _wa(ldb)
    out = fl.run(ldb, SETTINGS, now=NOW)
    assert out["unreachable"] == 1
    assert senders["ask"] == [], "nothing more is sent"
    fix = _fixes(ldb)[fl.WHATSAPP_UNDELIVERED]
    assert fix.status == fl.UNREACHABLE
    (item,) = fl.unreachable_list(ldb)
    assert item["csp_id"] == CODE
    assert item["reasons"] == [
        f"WhatsApp did not reach the main number {MAIN}",
        "no other number in CSPDATA, the Calling sheet or Zoho",
        "no email address in CSPDATA"]
    assert fl.contact_status(ldb)["unreachable"] == 1


def test_bad_number_bad_alternate_and_bounced_email(ldb, senders, sheet):
    _csp(ldb, mobile="9812345601/ 9812345602")
    _wa(ldb)
    fl.run(ldb, SETTINGS, now=NOW)                   # tries the alternate
    _wa(ldb, phone=ALT, delivery="failed", at=NOW + timedelta(minutes=1))
    fl.run(ldb, SETTINGS, now=NOW + timedelta(minutes=10))   # emails the form
    assert senders["ask"][-1][1] == "email"
    _bounce(ldb)                                     # ... and it bounced
    asked_before = len(senders["ask"])
    out = fl.run(ldb, SETTINGS, now=NOW + timedelta(minutes=40))
    assert out["unreachable"] == 1
    assert len(senders["ask"]) == asked_before, \
        "no WhatsApp to the bad number asking for the email"
    fixes = _fixes(ldb)
    assert {f.status for f in fixes.values()} == {fl.UNREACHABLE}
    (item,) = fl.unreachable_list(ldb)
    assert item["reasons"] == [
        f"WhatsApp did not reach the main number {MAIN}",
        f"the alternate number {ALT} did not reach them either",
        "the email to loop@example.com bounced"]


def test_a_working_email_means_reachable(ldb, senders):
    _csp(ldb)
    _wa(ldb)
    out = fl.run(ldb, SETTINGS, now=NOW)
    assert out["unreachable"] == 0
    assert _fixes(ldb)[fl.WHATSAPP_UNDELIVERED].status == "asked"
    assert fl.unreachable_list(ldb) == []


def test_an_untried_alternate_comes_first(ldb, senders, sheet):
    _csp(ldb, mobile="9812345601/ 9812345602", email="")
    _wa(ldb)
    out = fl.run(ldb, SETTINGS, now=NOW)
    assert out["unreachable"] == 0
    assert _fixes(ldb)[fl.WHATSAPP_UNDELIVERED].status == "trying_alternate"


def test_a_new_number_in_cspdata_starts_it_again(ldb, senders):
    _csp(ldb, email="")
    _wa(ldb)
    fl.run(ldb, SETTINGS, now=NOW)
    assert _fixes(ldb)[fl.WHATSAPP_UNDELIVERED].status == fl.UNREACHABLE
    from app.models.csp_record import CSPRecord
    rec = ldb.execute(select(CSPRecord)).scalar_one()
    rec.mobile = "9812345699"
    ldb.commit()
    fl.run(ldb, SETTINGS, now=NOW + timedelta(minutes=30))
    fix = _fixes(ldb)[fl.WHATSAPP_UNDELIVERED]
    assert fix.status in ("done", "resent", "corrected")
    assert fix.corrected_value == "919812345699"
    assert fl.unreachable_list(ldb) == []


def test_a_new_alternate_is_found_on_the_daily_look(ldb, senders, monkeypatch):
    _csp(ldb, email="")
    _wa(ldb)
    fl.run(ldb, SETTINGS, now=NOW)
    monkeypatch.setattr(fl, "_zoho_numbers", lambda s, r: [ALT])
    fl.run(ldb, SETTINGS, now=NOW + timedelta(hours=1))
    assert _fixes(ldb)[fl.WHATSAPP_UNDELIVERED].status == fl.UNREACHABLE, \
        "looked at again only once a day"
    fl.run(ldb, SETTINGS, now=NOW + timedelta(hours=25))
    fix = _fixes(ldb)[fl.WHATSAPP_UNDELIVERED]
    assert (fix.status, fix.alternate) == ("trying_alternate", ALT)
