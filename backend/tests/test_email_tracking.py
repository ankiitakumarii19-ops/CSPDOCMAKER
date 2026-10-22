"""Every email to a CSP is tracked: sent / failed, opened, bounced (No. 127).

The mail server is a stand-in that keeps what it was given; no email is
sent. The bounce notice is a made-up one shaped like Gmail's.
"""

import smtplib
from email.mime.text import MIMEText

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.email_message import EmailMessage
from app.services import email_log, email_service, message_sender

pytestmark = pytest.mark.asyncio(loop_scope="session")


class FakeSMTP:
    sent = []
    fail = False

    def __init__(self, *a, **k):
        pass

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise smtplib.SMTPRecipientsRefused({"x": (550, b"no")})
        FakeSMTP.sent.append(msg)

    def quit(self):
        pass


@pytest.fixture
def mail(migrated_db, monkeypatch, tmp_path):
    s = get_settings()
    for name, value in (("email_method", "smtp"), ("smtp_username", "bot@eko.co.in"),
                        ("smtp_password", "x"), ("smtp_from_email", "bot@eko.co.in"),
                        ("public_app_url", "https://indev.eko.in/csp-docmaker")):
        monkeypatch.setattr(s, name, value)
        monkeypatch.setattr(email_service.settings, name, value)
    FakeSMTP.sent, FakeSMTP.fail = [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    engine = create_engine(s.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as db:
        db.execute(text("TRUNCATE email_messages"))
        db.commit()
        pdf = tmp_path / "ID Card.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        yield db, str(pdf)
        db.execute(text("TRUNCATE email_messages"))
        db.commit()
    engine.dispose()


def _rows(db):
    db.expire_all()
    return db.execute(select(EmailMessage).order_by(
        EmailMessage.sent_at)).scalars().all()


def _html(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode()
    return ""


async def test_a_documents_email_is_recorded_with_its_open_picture(mail):
    db, pdf = mail
    assert email_service.send_documents_email(
        to_email="asha@example.com", csp_name="Asha", csp_id="1A970001",
        doc_names=["ID Card"], doc_filepaths=[pdf])
    [row] = _rows(db)
    assert row.kind == "documents" and row.send_status == "sent"
    assert row.csp_id == "1A970001" and row.to_email == "asha@example.com"
    [msg] = FakeSMTP.sent
    assert msg["Message-ID"] == row.message_id
    assert f"/api/public/email-open/{row.track_token}.gif" in _html(msg)


async def test_a_failed_email_is_recorded_as_failed(mail):
    db, pdf = mail
    FakeSMTP.fail = True
    ok, why = message_sender._send_email(
        "bad@example.com", "Please confirm", "Namaste", kind="details_request",
        csp_id="1A970002", csp_name="Ravi")
    assert ok is False
    [row] = _rows(db)
    assert row.send_status == "failed" and row.kind == "details_request"
    assert row.send_error


async def test_opening_marks_it_and_counts(mail, client):
    db, pdf = mail
    message_sender._send_email("asha@example.com", "Hi", "Body",
                               kind="chat", csp_id="1A970003")
    [row] = _rows(db)
    for _ in range(2):
        r = await client.get(f"/api/public/email-open/{row.track_token}.gif")
        assert r.status_code == 200 and r.headers["content-type"] == "image/gif"
    [row] = _rows(db)
    assert row.opened_at is not None and row.open_count == 2
    r = await client.get("/api/public/email-open/" + "0" * 32 + ".gif")
    assert r.status_code == 200, "an unknown token still gets the picture"


async def test_a_bounce_notice_marks_the_email(mail):
    db, pdf = mail
    message_sender._send_email("gone@example.com", "Hi", "Body",
                               kind="details_request", csp_id="1A970004")
    [row] = _rows(db)
    notice = (
        "From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>\r\n"
        "Subject: Delivery Status Notification (Failure)\r\n"
        "Content-Type: multipart/report; report-type=delivery-status; "
        "boundary=B\r\n\r\n"
        "--B\r\nContent-Type: text/plain\r\n\r\n"
        "Address not found. The email account does not exist.\r\n"
        "--B\r\nContent-Type: message/delivery-status\r\n\r\n"
        "Final-Recipient: rfc822; gone@example.com\r\nStatus: 5.1.1\r\n"
        "--B\r\nContent-Type: text/rfc822-headers\r\n\r\n"
        f"Message-ID: {row.message_id}\r\nTo: gone@example.com\r\n"
        "--B--\r\n").encode()
    bounce = email_log.parse_bounce(notice)
    assert bounce.recipient == "gone@example.com"
    assert bounce.message_id == row.message_id
    assert email_log.apply_bounces(db, [bounce]) == 1
    [row] = _rows(db)
    assert row.bounced_at is not None and "does not exist" in row.bounce_reason
    plain = MIMEText("hello")
    plain["From"] = "someone@example.com"
    assert email_log.parse_bounce(plain.as_bytes()) is None


async def test_the_report_counts_by_kind_for_admins_only(mail, client):
    from app.services import jwt_service
    db, pdf = mail
    message_sender._send_email("a@example.com", "s", "b",
                               kind="details_request", csp_id="1A970005")
    FakeSMTP.fail = True
    message_sender._send_email("b@example.com", "s", "b",
                               kind="details_request", csp_id="1A970006")

    def h(role):
        return {"Authorization": "Bearer " + jwt_service.create_access_token(
            {"sub": f"{role}@eko.co.in", "role": role, "name": role})}
    assert (await client.get("/api/admin/email-messages",
                             headers=h("rm"))).status_code == 403
    body = (await client.get("/api/admin/email-messages",
                             headers=h("admin"))).json()
    c = body["counts"]["details_request"]
    assert c["sent"] == 1 and c["failed"] == 1 and c["not_opened"] == 1
    body = (await client.get("/api/admin/email-messages?status=failed",
                             headers=h("admin"))).json()
    assert [m["csp_id"] for m in body["messages"]] == ["1A970006"]
