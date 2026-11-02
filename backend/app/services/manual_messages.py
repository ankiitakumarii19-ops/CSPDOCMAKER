"""
CSP DocMaker — a message a person sends to a CSP (No. 174)

From Action Required (one CSP) and Messaging → Ask CSPs (many). Two kinds:

  * a CUSTOM message — any words, saved or typed, with {name}, {csp_id}
    and {missing_items} filled in for each CSP. On WhatsApp it goes inside
    the already-approved wording ("Namaste {name}, here is a message from
    Eko Bharat Ventures: <message> Thank you." — owner's choice 2 Nov 2026),
    on one line; by email, exactly as typed.
  * the DETAILS FORM — the usual "please confirm your details" message with
    a link (message_sender.ask_for_details), wording from Messaging.

Rules that stay (owner's choices, 2 Nov 2026):
  * nothing is sent to a CSP on hold (not live / not active);
  * an EXISTING CSP (in CSPDATA before the Calling / Lead import) may get a
    custom message, never the details form (D14);
  * only the server sends (a laptop copy never messages anyone), and a test
    copy never does (TEST_COPY).

Every send is logged: whatsapp_messages (with the words and who sent them)
or email_messages, plus an audit row "csp_message" with the text, channel,
result and the person.
"""

import logging
from typing import List, Optional

from sqlalchemy import select

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

WHATSAPP = "whatsapp"
EMAIL = "email"
DETAILS_FORM = "details_form"
CUSTOM = "custom"
PLACEHOLDERS = ("{name}", "{csp_id}", "{missing_items}")
EMAIL_SUBJECT = "A message from Eko Bharat Ventures"


def missing_labels(record) -> List[str]:
    """What this CSP could still give themselves (their own details)."""
    from app.services import field_ownership as fo

    return [fo.label_of(f) for f in fo.missing(record)[fo.CSP]]


def render(text: str, record) -> str:
    """Fill the three placeholders; anything else is left as written."""
    missing = missing_labels(record)
    out = text or ""
    for token, value in (("{name}", record.name or "CSP"),
                         ("{csp_id}", record.csp_id),
                         ("{missing_items}", ", ".join(missing) or "nothing")):
        out = out.replace(token, value)
    return out


def is_existing(session, record) -> bool:
    """In CSPDATA before the Calling / Lead import (D14) — not a Calling-sheet
    copy (imported_as baseline) and not a new one."""
    from app.models.source_sheet import SourceSheetState

    if (record.origin or "") != "baseline":
        return False
    code = record.csp_code or record.csp_id
    imported = session.execute(select(SourceSheetState.imported_as).where(
        SourceSheetState.csp_code == code)).scalar()
    return not imported


def refusal(on_hold: Optional[str], existing: bool, kind: str) -> Optional[str]:
    """Why this CSP may not get this message, or None (owner's rules,
    2 Nov 2026; golden cases MSG-*)."""
    if on_hold:
        return f"on hold — nothing is sent: {on_hold}"
    if kind == DETAILS_FORM and existing:
        return ("an existing CSP (in CSPDATA before the import) is never sent "
                "the details form — send a custom message instead")
    return None


def channels(settings=None) -> List[dict]:
    """The ways a message can go, whether each can send now, and why not."""
    from app.config import get_settings
    from app.services import email_service, message_sender

    s = settings or get_settings()
    server = message_sender.link_is_reachable(s.public_app_url)
    not_here = ("Only the server sends — this copy of the app is not on a "
                "public address (PUBLIC_APP_URL).")
    if getattr(s, "test_copy", False):
        not_here = "This is the test copy (TEST_COPY): it never sends."
    wa_ready = bool(getattr(s, "whatsapp_platform_url", ""))
    mail_ready = bool((s.smtp_username and s.smtp_password)
                      or getattr(s, "email_method", "") == "gmail_api")
    return [
        {"kind": WHATSAPP, "label": "WhatsApp",
         "can_send": server and wa_ready and not getattr(s, "test_copy", False),
         "why_not": (not_here if not server or getattr(s, "test_copy", False)
                     else "" if wa_ready
                     else "WHATSAPP_PLATFORM_URL is not set on the server.")},
        {"kind": EMAIL, "label": "Email",
         "can_send": server and mail_ready and not email_service.paused(),
         "why_not": (not_here if not server
                     else email_service.PAUSED_REASON if email_service.paused()
                     else "" if mail_ready
                     else "The sender's email settings (SMTP) are not set.")},
        {"kind": "sms", "label": "SMS", "can_send": False,
         "why_not": "Not part of this app (no SMS provider)."},
        {"kind": "in_app", "label": "In-app chat", "can_send": False,
         "why_not": "CSPs do not sign in to this app, so there is no in-app "
                    "chat with them."},
    ]


def _audit(session, record, by: str, channel: str, text: str,
           result: dict) -> None:
    session.add(AuditLog(
        action="csp_message", resource_type="csp", resource_id=record.csp_id,
        csp_id=record.csp_id, result="success" if result["sent"] else "failure",
        metadata_json={"by": by, "channel": channel, "kind": result["kind"],
                       "text": (text or "")[:1000],
                       "reason": (result.get("reason") or "")[:300]}))


def send(session, record, *, kind: str, channel: str, text: str = "",
         by: str, wa=None) -> dict:
    """Send one CSP one message. Never raises for a refusal: the result says
    {csp_id, sent, reason, channel, kind, text}. The caller commits."""
    from app.services import (assistant_tools, csp_replies, message_log,
                              message_sender, send_reason, whatsapp_platform)
    from app.models.whatsapp_message import KIND_OTHER

    wa = wa or whatsapp_platform
    result = {"csp_id": record.csp_id, "sent": False, "reason": "",
              "channel": channel, "kind": kind, "text": ""}

    def refuse(reason: str) -> dict:
        result["reason"] = reason
        _audit(session, record, by, channel, text, result)
        return result

    why = refusal(record.send_hold,
                  kind == DETAILS_FORM and is_existing(session, record), kind)
    if why:
        return refuse(why)
    available = {c["kind"]: c for c in channels()}
    if channel not in (WHATSAPP, EMAIL) or not available[channel]["can_send"]:
        return refuse(available.get(channel, {}).get("why_not")
                      or f"{channel!r} cannot send")

    if kind == DETAILS_FORM:
        try:
            configured = message_sender.choose_channel(session, kind=channel)
        except message_sender.NoChannel:
            return refuse(f"no {channel} channel is set up on Messaging → "
                          f"Channels")
        with send_reason.because(send_reason.MANUAL):
            outcome = message_sender.ask_for_details(
                session, record, channel=configured, manual=True,
                verify=True, allow_email=channel == EMAIL)
        result["sent"] = bool(outcome.get("sent"))
        result["reason"] = outcome.get("reason") or ""
        result["text"] = "Details form (the usual wording, with a new link)"
        _audit(session, record, by, channel, result["text"], result)
        return result

    body = render(text, record).strip()
    if not body:
        return refuse("the message is empty")
    if channel == WHATSAPP:
        one_line = csp_replies.clean(body)
        if len(one_line) < len(" ".join(body.split())):
            return refuse(f"too long for one WhatsApp (at most "
                          f"{csp_replies.MAX_CHARS} characters)")
        phone = whatsapp_platform.phone_for_whatsapp(record.mobile or "")
        if not phone:
            return refuse("no usable WhatsApp number")
        outcome = wa.send(phone, assistant_tools.WHATSAPP_WORDING,
                          {"name": record.name or "CSP", "message": one_line},
                          source_name=message_log.source_name("chat", record.csp_id))
        with send_reason.because(send_reason.MANUAL):
            message_log.record(session, kind=KIND_OTHER, mobile=phone,
                               outcome=outcome, csp_id=record.csp_id,
                               csp_name=record.name or "",
                               body_text=one_line, sent_by=by)
        result["text"] = one_line
        result["sent"] = outcome.get("status") == wa.SENT
        if outcome.get("status") == wa.PENDING:
            result["reason"] = "WhatsApp is checking the wording — sent once approved"
        elif not result["sent"]:
            result["reason"] = outcome.get("reason") or "not sent"
    else:
        to = (record.email or "").strip()
        if not to:
            return refuse("no email address")
        with send_reason.because(send_reason.MANUAL):
            ok, why = message_sender._send_email(
                to, EMAIL_SUBJECT, body, kind="other",
                csp_id=record.csp_id, csp_name=record.name or "")
        result.update(sent=ok, reason=why or "", text=body)
    _audit(session, record, by, channel, result["text"], result)
    logger.info("manual_messages: %s → %s by %s: %s", channel, record.csp_id,
                by, "sent" if result["sent"] else result["reason"])
    return result


def sent_to(session, csp_id: str, limit: int = 50) -> List[dict]:
    """Every message a person sent this CSP, newest first (the log)."""
    rows = session.execute(
        select(AuditLog).where(AuditLog.action == "csp_message",
                               AuditLog.csp_id == csp_id)
        .order_by(AuditLog.created_at.desc()).limit(limit)).scalars().all()
    out = []
    for r in rows:
        m = r.metadata_json or {}
        out.append({"at": r.created_at.isoformat() if r.created_at else None,
                    "by": m.get("by"), "channel": m.get("channel"),
                    "kind": m.get("kind"), "text": m.get("text"),
                    "sent": r.result == "success", "reason": m.get("reason")})
    return out


def preview(session, record, kind: str, text: str) -> dict:
    """What this CSP would get, and whether they can get it."""
    blocked: Optional[str] = None
    if record.send_hold:
        blocked = f"on hold: {record.send_hold}"
    elif kind == DETAILS_FORM and is_existing(session, record):
        blocked = "existing CSP — never sent the details form"
    if kind == DETAILS_FORM:
        shown = "The usual details message with a new link (wording on Messaging)."
    else:
        shown = render(text, record)
    from app.services import assistant_tools, csp_replies
    return {"csp_id": record.csp_id, "name": record.name or "",
            "email_text": shown,
            "whatsapp_text": (shown if kind == DETAILS_FORM else
                              assistant_tools.WHATSAPP_WORDING.format(
                                  name=record.name or "CSP",
                                  message=csp_replies.clean(shown))),
            "blocked": blocked}
