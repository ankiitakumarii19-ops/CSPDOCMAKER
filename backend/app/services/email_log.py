"""
CSP DocMaker — recording every email sent to a CSP (tracker No. 127)

  * tracker()  — a new token, the Message-ID to put on the email, and the
                 1-pixel picture whose loading marks it "opened";
  * record()   — the row, written as the email is sent (sent / failed);
  * bounces()  — reads Gmail's "delivery failed" notices from the sending
                 inbox and marks those emails bounced.

Recording never stops an email: a failure to record is logged with its
traceback and the email still goes.
"""

import email
import imaplib
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

_engine = None


@dataclass
class Tracker:
    token: str
    message_id: str
    pixel_html: str


def _public_base() -> Optional[str]:
    url = (get_settings().public_app_url or "").rstrip("/")
    if not url or "localhost" in url or "127.0.0.1" in url:
        return None          # a phone could never load it
    return url


def tracker(from_email: str = "") -> Tracker:
    token = uuid.uuid4().hex
    domain = (from_email.split("@")[-1] if "@" in (from_email or "")
              else "cspdocmaker")
    base = _public_base()
    pixel = (f'<img src="{base}/api/public/email-open/{token}.gif" '
             'width="1" height="1" alt="" style="display:block;width:1px;'
             'height:1px;border:0" />') if base else ""
    return Tracker(token, f"<{token}@{domain}>", pixel)


def _session():
    global _engine
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    if _engine is None:
        _engine = create_engine(get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"),
            pool_pre_ping=True)
    return Session(_engine)


def record(*, kind: str, to_email: str, subject: str, ok: bool,
           error: str = "", track: Optional[Tracker] = None,
           csp_id: Optional[str] = None, csp_name: Optional[str] = None
           ) -> None:
    """One row for one email. Never raises."""
    from app.models.email_message import FAILED, SENT, EmailMessage
    track = track or tracker()
    try:
        with _session() as s:
            s.add(EmailMessage(
                csp_id=csp_id, csp_name=(csp_name or "")[:300] or None,
                to_email=(to_email or "")[:320], kind=kind,
                subject=(subject or "")[:500], message_id=track.message_id,
                track_token=track.token, send_status=SENT if ok else FAILED,
                send_error=None if ok else (error or "not sent")[:2000]))
            s.commit()
    except Exception as e:
        logger.error("email_log.record: could not record the %s email to "
                     "CSP %s: %s: %s", kind, csp_id, type(e).__name__, e,
                     exc_info=True)


# ---- bounces -------------------------------------------------------------------------

BOUNCE_SENDERS = ("mailer-daemon", "postmaster")
FINAL_RECIPIENT = re.compile(r"Final-Recipient:\s*rfc822;\s*([^\s<>]+)", re.I)
ORIGINAL_ID = re.compile(r"^Message-ID:\s*(<[^>]+>)", re.I | re.M)


@dataclass
class Bounce:
    recipient: Optional[str]
    message_id: Optional[str]
    reason: str


def parse_bounce(raw: bytes) -> Optional[Bounce]:
    """A Gmail / mail-server "delivery failed" notice, or None."""
    msg = email.message_from_bytes(raw)
    sender = parseaddr(msg.get("From", ""))[1].lower()
    if not any(s in sender for s in BOUNCE_SENDERS):
        return None
    text_parts, ids = [], []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("text/plain", "message/delivery-status"):
            payload = part.get_payload(decode=True)
            if payload is None and part.is_multipart():
                payload = "\n".join(str(p) for p in part.get_payload()).encode()
            text_parts.append((payload or b"").decode("utf-8", "replace"))
        if ctype in ("message/rfc822", "text/rfc822-headers"):
            ids += ORIGINAL_ID.findall(str(part))
    text = "\n".join(text_parts)
    recipient = FINAL_RECIPIENT.search(text)
    reason = ""
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith(("diagnostic-code:", "status:")) or \
                "does not exist" in line.lower() or "not found" in line.lower():
            reason = line[:500]
            break
    return Bounce(recipient.group(1).lower() if recipient else None,
                  ids[0] if ids else None,
                  reason or (msg.get("Subject", "") or "delivery failed")[:500])


def fetch_bounces(days: int = 3) -> List[Bounce]:
    """Bounce notices in the sending Gmail inbox from the last few days.
    Read-only (BODY.PEEK leaves them unread). Raises on login failure."""
    s = get_settings()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%d-%b-%Y")
    found = []
    box = imaplib.IMAP4_SSL(s.imap_host, timeout=30)
    try:
        box.login(s.smtp_username, s.smtp_password)
        box.select("INBOX", readonly=True)
        typ, data = box.search(None, f'(SINCE "{since}" OR FROM '
                                     f'"mailer-daemon" FROM "postmaster")')
        for num in (data[0] or b"").split():
            typ, parts = box.fetch(num, "(BODY.PEEK[])")
            raw = parts[0][1] if parts and isinstance(parts[0], tuple) else b""
            bounce = parse_bounce(raw)
            if bounce:
                found.append(bounce)
    finally:
        try:
            box.logout()
        except Exception as e:
            logger.warning("email_log: IMAP logout failed: %s", e)
    return found


def apply_bounces(session, bounces: List[Bounce]) -> int:
    """Mark the emails these notices are about. Returns how many."""
    from sqlalchemy import select

    from app.models.email_message import SENT, EmailMessage
    marked = 0
    for b in bounces:
        row = None
        if b.message_id:
            row = session.execute(select(EmailMessage).where(
                EmailMessage.message_id == b.message_id)).scalars().first()
        if row is None and b.recipient:
            row = session.execute(select(EmailMessage).where(
                EmailMessage.to_email.ilike(b.recipient),
                EmailMessage.send_status == SENT)
                .order_by(EmailMessage.sent_at.desc())).scalars().first()
        if row is not None and row.bounced_at is None:
            row.bounced_at = datetime.now(timezone.utc)
            row.bounce_reason = b.reason
            marked += 1
    session.commit()
    return marked
