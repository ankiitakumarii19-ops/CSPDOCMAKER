"""The contact loop's earlier sends get their reason; its status in one line
(No. 158).
"""

import subprocess
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.models.email_message import EmailMessage
from app.models.feedback_loop import ContactFix
from app.models.whatsapp_message import WhatsAppMessage
from app.services import feedback_loops as fl
from tests.conftest import BACKEND_DIR
from tests.test_feedback_loops import ldb  # noqa: F401
from tests.test_field_quality import _engine, qdb  # noqa: F401

T = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)
MIGRATION = "d7f9b3c5e1a8"


def _rerun_migration():
    for args in (("downgrade", "b1d3f5a7c9e2"), ("upgrade", "head")):
        subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR,
                       check=True, capture_output=True)


def _wa(db, code, phone, minutes, kind="data_request"):
    db.add(WhatsAppMessage(csp_id=code, phone=phone, kind=kind, source="t",
                           send_status="sent", sent_at=T + timedelta(minutes=minutes)))


def _mail(db, code, minutes, kind="details_request", token="t"):
    db.add(EmailMessage(csp_id=code, to_email="x@example.com", kind=kind,
                        subject="s", track_token=token, send_status="sent",
                        sent_at=T + timedelta(minutes=minutes)))


def test_earlier_contact_sends_are_labelled(ldb):
    ldb.add_all([
        ContactFix(csp_id="1A999001", problem="email_bounced",
                   bad_value="bad@example.com", status="asked", asked_at=T,
                   asked_via="whatsapp"),
        ContactFix(csp_id="1A999002", problem="whatsapp_undelivered",
                   bad_value="919812345601", status="asked", asked_at=T,
                   asked_via="email"),
        ContactFix(csp_id="1A999003", problem="whatsapp_undelivered",
                   bad_value="919812345601", status="done",
                   alternates_tried=["919812345602"]),
    ])
    _wa(ldb, "1A999001", "919800000001", 1)          # the bounce ask
    _wa(ldb, "1A999001", "919800000001", 600)        # much later: not it
    _mail(ldb, "1A999002", 1, token="t1")            # the email ask
    _wa(ldb, "1A999003", "919812345602", 30)         # to the alternate
    _wa(ldb, "1A999003", "919812345601", 0)          # the main number: not it
    ldb.commit()

    _rerun_migration()
    ldb.expire_all()
    got = {(m.csp_id, m.phone, m.sent_at.minute if m.sent_at.hour == 9 else -1):
           m.sent_because for m in ldb.execute(select(WhatsAppMessage)).scalars()}
    assert got[("1A999001", "919800000001", 1)] == "email_bounced"
    assert got[("1A999001", "919800000001", -1)] is None
    assert got[("1A999003", "919812345602", 30)] == "alternate_number"
    assert got[("1A999003", "919812345601", 0)] is None
    mail = ldb.execute(select(EmailMessage).where(
        EmailMessage.csp_id == "1A999002")).scalar_one()
    assert mail.sent_because == "whatsapp_unreachable"


def test_the_contact_status_in_one_line(ldb):
    ldb.add_all([
        ContactFix(csp_id="1A999011", problem="email_bounced", bad_value="a",
                   status="corrected", note="waiting: emails are paused (EMAILS_PAUSED)"),
        ContactFix(csp_id="1A999012", problem="email_bounced", bad_value="b",
                   status="corrected", note="waiting: emails are paused (EMAILS_PAUSED)"),
        ContactFix(csp_id="1A999013", problem="whatsapp_undelivered", bad_value="c",
                   status="open", note="no email address to ask on"),
        ContactFix(csp_id="1A999014", problem="email_bounced", bad_value="d",
                   status="resent"),
        ContactFix(csp_id="1A999015", problem="email_bounced", bad_value="e",
                   status="stopped"),
    ])
    ldb.commit()
    status = fl.contact_status(ldb)
    assert (status["found"], status["in_progress"], status["fixed"],
            status["stopped"]) == (5, 3, 1, 1)
    assert status["waiting"][0] == {
        "note": "waiting: emails are paused (EMAILS_PAUSED)", "count": 2}
    assert {"note": "no email address to ask on", "count": 1} in status["waiting"]
