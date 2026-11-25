"""Every CSP gets the WhatsApp, even when it fails (No. 237).

The owner's rule, 25 Nov 2026: a failed WhatsApp is tried again — no giving
up; when the main number does not take it, the alternate number(s), then
email; an alternate-number column in CSPDATA may hold two numbers split by
"/"; "mailto:" in front of an email is dropped; and a daily email says how
many messages went today, how many times each CSP has been contacted, and
who cannot be contacted and why. Every send is a stand-in.
"""

import csv
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.email_message import EmailMessage
from app.models.feedback_loop import ContactFix
from app.models.whatsapp_message import WhatsAppMessage
from app.services import contact_report as cr
from app.services import csp_mapping
from app.services import feedback_loops as fl
from app.services import resend_failed as rf
from app.services import settings_catalog
from tests.test_feedback_loops import SETTINGS as LOOP, ldb, senders  # noqa: F401
from tests.test_feedback_loops import _csp as _record
from tests.test_field_quality import _engine, qdb  # noqa: F401

NOW = datetime.now(timezone.utc)
CODE = "1A996001"
MAIN = "919812345601"
RETRY = SimpleNamespace(resend_failed_batch=20, verify_old_csps_enabled=False,
                        calling_sheet_id="")
FILE_TYPE = ("platform accepted but sent 0: (#546) The type of file you're "
             "trying to attach isn't allowed.")
PLATFORM_DOWN = "WhatsApp platform unreachable: ConnectError: no route"


def _csp(db, code=CODE, **kw):
    """A CSP whose documents were made (so a documents message can go)."""
    import uuid
    from app.models.processing_job import ProcessingJob
    _record(db, code=code, **kw)
    db.add(ProcessingJob(job_id=f"job-{uuid.uuid4().hex[:12]}", csp_id=code,
                         workflow_type="new_csp"))
    db.commit()


def _failed(db, hours_ago=1.0, kind="documents_ready", error=FILE_TYPE,
            phone=MAIN, code=CODE, status="failed"):
    m = WhatsAppMessage(csp_id=code, phone=phone, kind=kind, source="t",
                        send_status=status, send_error=error,
                        sent_at=NOW - timedelta(hours=hours_ago))
    db.add(m)
    db.commit()
    return m


def _tries(db, n, error=FILE_TYPE, phone=MAIN, start_hours_ago=30.0):
    """n failed tries, oldest first, each a few hours apart."""
    return [_failed(db, hours_ago=start_hours_ago - 5 * i, error=error,
                    phone=phone) for i in range(n)]


# ---- "mailto:" ------------------------------------------------------------

@pytest.mark.parametrize("cell,email", [
    ("mailto:csp.own@example.com", "csp.own@example.com"),
    ("MailTo: a.b@example.com", "a.b@example.com"),
    ("mailto:x@example.com?subject=Hi", "x@example.com"),
    (" plain@example.com ", "plain@example.com"),
    ("", ""),
    (None, ""),
])
def test_mailto_is_dropped(cell, email):
    assert csp_mapping.clean_email(cell) == email


def test_the_sheet_row_gives_the_clean_email():
    mapped = csp_mapping.map_sheet_row({"CSP Code": "1A850674",
                                        "CSP Email Id": "mailto:csp.own@example.com"})
    assert mapped["email"] == "csp.own@example.com"


def test_the_contact_loop_sees_the_clean_email():
    assert fl._email("mailto:CSP.Own@example.com") == "csp.own@example.com"


# ---- never giving up --------------------------------------------------------

def test_a_month_old_failure_is_still_sent_again(ldb, senders):
    """1A850674: two documents-ready WhatsApps failed on 17 Oct and were
    never tried again (the 7-day limit). Now they are — to the number on the
    record today."""
    _csp(ldb, mobile="9812345677")
    _failed(ldb, hours_ago=24 * 39, phone="919812345688")
    _failed(ldb, hours_ago=24 * 39 - 0.05, phone="919812345688",
            error="Could not download header media: Read timed out")
    out = rf.run(ldb, RETRY, now=NOW)
    assert out["sent"] == 1
    assert senders["whatsapp"] == [("9812345677", ["CSP ID Card"])]


def test_the_number_is_handed_over_after_5_number_failures(ldb, senders):
    _csp(ldb)
    tries = _tries(ldb, 5)
    assert rf.run(ldb, RETRY, now=NOW)["sent"] == 0
    assert senders["whatsapp"] == [], "not sent to the same number again"
    ldb.expire_all()
    assert tries[-1].retry_status == rf.HANDED_OVER
    assert "alternate number, then email" in tries[-1].retry_note
    # ... and the contact loop takes it.
    assert fl.find_problems(ldb) == 1
    ldb.commit()
    fix = ldb.execute(select(ContactFix)).scalar_one()
    assert (fix.problem, fix.bad_value, fix.failed_kind) == (
        fl.WHATSAPP_UNDELIVERED, MAIN, "documents_ready")


def test_four_failures_are_still_tried_on_the_main_number(ldb, senders):
    _csp(ldb)
    _tries(ldb, 4)
    assert rf.run(ldb, RETRY, now=NOW)["sent"] == 1
    assert senders["whatsapp"] == [("9812345601", ["CSP ID Card"])]


def test_a_platform_outage_never_hands_the_number_over(ldb, senders):
    _csp(ldb)
    tries = _tries(ldb, 8, error=PLATFORM_DOWN, start_hours_ago=40)
    assert rf.run(ldb, RETRY, now=NOW)["sent"] == 1
    ldb.expire_all()
    assert tries[-1].retry_status is None


def test_tries_to_an_older_number_do_not_count(ldb, senders):
    _csp(ldb)
    _tries(ldb, 4, phone="919812345688", start_hours_ago=60)
    _tries(ldb, 2)
    assert rf.number_failures(
        ldb.execute(select(WhatsAppMessage).order_by(WhatsAppMessage.sent_at))
        .scalars().all(), NOW) == 2
    assert rf.run(ldb, RETRY, now=NOW)["sent"] == 1


def test_handed_over_goes_to_the_alternate_then_email(ldb, senders):
    _csp(ldb, mobile="9812345601 / 9812345602")
    _tries(ldb, 5)
    rf.run(ldb, RETRY, now=NOW)                       # hands over
    fl.run(ldb, LOOP, now=NOW)                        # the alternate
    assert senders["whatsapp"] == [("919812345602", ["CSP ID Card"])]
    fix = ldb.execute(select(ContactFix)).scalar_one()
    assert fix.status == "trying_alternate"


def test_with_no_alternate_the_csp_is_emailed(ldb, senders):
    _csp(ldb)
    _tries(ldb, 5)
    rf.run(ldb, RETRY, now=NOW)
    fl.run(ldb, LOOP, now=NOW)
    assert senders["ask"] == [(CODE, "email", True, True)]


def test_the_setting_replaces_the_give_up_days():
    assert "resend_give_up_days" not in settings_catalog.BY_KEY
    s = settings_catalog.BY_KEY["resend_handover_tries"]
    assert (s.min, s.max) == (1, 20)
    from app.config import get_settings
    assert get_settings().server.resend_handover_tries == 5


# ---- the alternate-number column in CSPDATA ("/" between two) ------------

def test_the_alternate_column_is_found():
    headings = ["CSP Code", "CSP Mobile Number", "Alternate Number",
                "DC Contact Number", "ASM Contact Number", "Branch Contact Number"]
    assert fl.sheet_alternate_columns(headings) == ["Alternate Number"]


def test_two_alternates_split_by_slash_are_both_tried_in_order(
        ldb, senders, monkeypatch):
    monkeypatch.setattr(fl, "_csp_sheet_rows", lambda: [{
        "CSP Code": CODE, "CSP Mobile Number": "9812345601",
        "Alternate Number": "9812345603 / 9812345604",
        "DC Contact Number": "9000000999"}])
    _csp(ldb)
    fl._calling_cache.clear()
    record = SimpleNamespace(csp_id=CODE, csp_code=CODE, mobile="9812345601")
    assert fl.alternate_numbers(record) == ["919812345603", "919812345604"]
    _tries(ldb, 5)
    rf.run(ldb, RETRY, now=NOW)
    fl.run(ldb, LOOP, now=NOW)
    assert senders["whatsapp"] == [("919812345603", ["CSP ID Card"])]
    fix = ldb.execute(select(ContactFix)).scalar_one()
    # The first alternate did not reach the phone: the second one is next.
    m = WhatsAppMessage(csp_id=CODE, phone="919812345603", kind="documents_ready",
                        source="t", send_status="sent", delivery_status="failed",
                        sent_at=NOW + timedelta(minutes=1))
    ldb.add(m)
    ldb.commit()
    fl.run(ldb, LOOP, now=NOW + timedelta(minutes=10))
    ldb.expire_all()
    assert senders["whatsapp"][-1] == ("919812345604", ["CSP ID Card"])
    assert fix.alternates_tried == ["919812345603", "919812345604"]


def test_an_unreadable_sheet_means_no_sheet_alternates(monkeypatch):
    def boom():
        raise RuntimeError("Google is down")
    monkeypatch.setattr(fl, "_csp_sheet_rows", boom)
    fl._calling_cache.clear()
    record = SimpleNamespace(csp_id=CODE, csp_code=CODE, mobile="9812345601")
    assert fl.alternate_numbers(record) == []


# ---- the daily contact email -----------------------------------------------

@pytest.fixture
def evening(monkeypatch):
    """Today at 20:30 India time, so 'today' holds the last few hours."""
    from app.workers.verify_old_csps_worker import send_zone
    local = NOW.astimezone(send_zone())
    return local.replace(hour=20, minute=30).astimezone(timezone.utc)


def test_what_the_daily_email_says(ldb, evening):
    _csp(ldb, code="1A000001", name="Asha")
    _csp(ldb, code="1A000002", name="Bina", mobile="", email="")
    _csp(ldb, code="1A000003", name="Chandan")
    now = evening
    for code in ("1A000001",):
        ldb.add(WhatsAppMessage(csp_id=code, phone=MAIN, kind="documents_ready",
                                source="t", send_status="sent",
                                delivery_status="read",
                                sent_at=now - timedelta(hours=1)))
        ldb.add(WhatsAppMessage(csp_id=code, phone=MAIN, kind="data_request",
                                source="t", send_status="sent",
                                delivery_status="read",
                                sent_at=now - timedelta(days=3)))
    ldb.add(EmailMessage(csp_id="1A000001", to_email="a@example.com",
                         kind="documents", subject="s", track_token="t-a",
                         send_status="sent", sent_at=now - timedelta(hours=2)))
    ldb.add(WhatsAppMessage(csp_id="1A000003", phone=MAIN, kind="documents_ready",
                            source="t", send_status="failed",
                            send_error=FILE_TYPE,
                            sent_at=now - timedelta(hours=3)))
    ldb.add(WhatsAppMessage(csp_id="1A000003", phone=MAIN, kind="other",
                            source="t", send_status="sent", is_test=True,
                            sent_at=now - timedelta(hours=1)))
    ldb.commit()

    data = cr.gather(ldb, now)
    assert data["today"] == {"whatsapp_sent": 1, "whatsapp_failed": 1,
                             "whatsapp_waiting": 0, "emails_sent": 1,
                             "emails_failed": 0, "total_sent": 2}, \
        "a test message never counts"
    rows = {r["csp_id"]: r for r in data["contacted_today"]}
    assert rows["1A000001"]["today_sent"] == 2
    assert rows["1A000001"]["in_all"] == 3, "2 WhatsApps + 1 email in all"
    assert rows["1A000003"]["today_failed"] == 1
    cannot = {r["csp_id"]: r for r in data["cannot"]}
    assert set(cannot) == {"1A000002", "1A000003"}
    assert cannot["1A000002"]["status"] == "nothing to send to"
    assert cannot["1A000003"]["status"] == "still trying"
    assert "type of file" in cannot["1A000003"]["why"][0]
    assert cannot["1A000003"]["why"][1] == "will be sent again"

    text = cr.body(data, "CSPdocMaker")
    assert "Messages that went out today: 2" in text
    assert "1A000001 Asha — 2 today" in text
    assert "contacted 3 times in all" in text
    assert "CSPs we cannot contact: 2" in text
    assert "no usable mobile number and no email address" in text

    table = list(csv.DictReader(io.StringIO(
        cr.csv_bytes(data["full"]).decode("utf-8-sig"))))
    by_code = {r["CSP code"]: r for r in table}
    assert by_code["1A000001"]["Times contacted"] == "3"
    assert by_code["1A000002"]["Status"] == "nothing to send to"
    assert by_code["1A000003"]["Failed tries"] == "1"


def test_a_csp_no_way_reaches_is_listed_with_why(ldb, senders, evening):
    _csp(ldb, email="")
    _tries(ldb, 5)
    rf.run(ldb, RETRY, now=NOW)
    fl.run(ldb, LOOP, now=NOW)
    data = cr.gather(ldb, evening)
    (item,) = data["cannot"]
    assert item["status"] == "can't reach — every way tried"
    assert f"WhatsApp did not reach the main number {MAIN}" in item["why"]
    assert "no email address in CSPDATA" in item["why"]


def test_the_daily_email_goes_once_a_day_after_its_hour(ldb, monkeypatch,
                                                         evening):
    from app.config import get_settings
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "link_is_reachable", lambda url: True)
    monkeypatch.setattr(get_settings().server, "test_copy", False)
    monkeypatch.setattr(get_settings().server, "contact_report_to",
                        "owner@example.com")
    _csp(ldb)
    sent = []

    def send(to, subject, text, data, filename):
        sent.append((to, subject, text, data, filename))
        return True, ""
    early = evening - timedelta(hours=2)              # 18:30
    assert cr.run(ldb, now=early, send=send) == {"skipped": "not the hour yet"}
    out = cr.run(ldb, now=evening, send=send)
    assert out["sent_to"] == ["owner@example.com"]
    (to, subject, text, data, filename) = sent[0]
    assert "messages today" in subject and "cannot be contacted" in subject
    assert filename.startswith("csp-contacts-") and filename.endswith(".csv")
    assert data.startswith("﻿".encode("utf-8"))
    assert cr.run(ldb, now=evening + timedelta(minutes=30), send=send) == {
        "skipped": "already sent today"}


def test_a_failed_daily_email_is_tried_again(ldb, monkeypatch, evening):
    from app.config import get_settings
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "link_is_reachable", lambda url: True)
    monkeypatch.setattr(get_settings().server, "test_copy", False)
    monkeypatch.setattr(get_settings().server, "contact_report_to",
                        "owner@example.com")
    out = cr.run(ldb, now=evening, send=lambda *a: (False, "SMTP down"))
    assert out["sent_to"] == [] and out["failed"] == {"owner@example.com": "SMTP down"}
    assert cr.due(ldb, evening + timedelta(minutes=30)) is None


def test_a_laptop_sends_no_daily_email(ldb, evening):
    out = cr.run(ldb, now=evening, send=lambda *a: pytest.fail("sent"))
    assert "not the server" in out["skipped"]


def test_the_csv_is_attached(monkeypatch):
    """The attachment really is in the email that SMTP would send."""
    from app.services import email_service
    captured = {}

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            captured["msg"] = msg

        def quit(self):
            pass
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_service.settings, "smtp_username", "u@example.com")
    monkeypatch.setattr(email_service.settings, "smtp_password", "x")
    monkeypatch.setattr(email_service.settings, "email_method", "smtp")
    assert email_service.send_with_attachment(
        "owner@example.com", "Daily", "hello", b"a,b\n1,2\n", "c.csv", "text/csv")
    msg = captured["msg"]
    names = [p.get_filename() for p in msg.walk() if p.get_filename()]
    assert names == ["c.csv"]
    assert msg["To"] == "owner@example.com"
