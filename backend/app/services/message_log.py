"""
CSP DocMaker — the record of every WhatsApp sent, and keeping it current

Tracker No. 110 (15 Oct 2026). Three jobs:

  record()   called the moment a WhatsApp is sent (or refused), so every
             attempt is on the record — including the ones that never left.

  refresh()  run every few minutes (workers.refresh_whatsapp_messages) and
             from the screen's Refresh button. Asks Eko's WhatsApp platform:
               * which of this app's sends it knows about that are not on the
                 record yet (its send history) — so a send made before this
                 record existed, or by a path that forgot to record, still
                 shows up;
               * Meta's delivered / read / failed status of each recent send;
               * the WhatsApp replies people sent back.
             And looks here for details forms that were filled in.

  report()   the numbers and rows the screen shows.

The platform's history and inbox are shared by every Eko team using it, so
only sends named "CSPdocMaker …" are taken, and only for CSPs this workspace
holds.

Nothing here may break a send: record() logs and returns None on failure.
refresh() never raises either — each failure is logged with its traceback,
kept on the message (check_error) and listed in what it returns.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import telemetry
from app.models.whatsapp_message import (
    DELIVERY_DELIVERED, DELIVERY_FAILED, DELIVERY_READ, DELIVERY_SENT,
    KIND_DATA_REQUEST, KIND_DOCUMENTS_READY, KIND_MISSING_DATA, KIND_OTHER,
    KINDS, RESPONSE_FORM, RESPONSE_WHATSAPP, SEND_FAILED, SEND_PENDING,
    SEND_REJECTED, SEND_SENT, WhatsAppMessage,
)

logger = logging.getLogger(__name__)

# Sent but still not on the phone after this long counts as not received:
# Meta keeps trying for a while, but by then the phone is off, not on
# WhatsApp, or the number is wrong.
NOT_RECEIVED_AFTER = timedelta(hours=24)

# At most this many delivery checks per refresh, so one refresh cannot hold
# the worker for long; the rest are checked next time, oldest-checked first.
MAX_CHECKS_PER_REFRESH = 200

# The platform's "source name" for each kind, followed by the CSP code.
# message_sender, documents_whatsapp and the test command name their sends
# this way; the send history is read back with the same names.
SOURCE_PREFIXES = (
    ("CSPdocMaker TEST details missing ", KIND_MISSING_DATA, True),
    ("CSPdocMaker TEST details request ", KIND_DATA_REQUEST, True),
    ("CSPdocMaker details missing ", KIND_MISSING_DATA, False),
    ("CSPdocMaker details request ", KIND_DATA_REQUEST, False),
    ("CSPdocMaker documents ", KIND_DOCUMENTS_READY, False),
)


def source_name(kind: str, csp_id: str, *, test: bool = False) -> str:
    """What a send is called on the platform; read back by parse_source."""
    for prefix, k, is_test in SOURCE_PREFIXES:
        if k == kind and is_test == test:
            return prefix + csp_id
    return f"CSPdocMaker {kind} {csp_id}"


def parse_source(name: str):
    """(kind, csp_id, is_test) from a source name, or None if not ours."""
    for prefix, kind, is_test in SOURCE_PREFIXES:
        if (name or "").startswith(prefix):
            csp_id = name[len(prefix):].strip()
            return (kind, csp_id, is_test) if csp_id else None
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def json_objects(text: str) -> List[dict]:
    """Every JSON object in a text that holds several back to back.

    The platform answers its list tools (send history, incoming messages)
    as JSON objects written one after another, not as one JSON array.
    Raises ValueError on anything that is not such a sequence, so a changed
    answer is reported rather than read as "nothing".
    """
    decoder, i, out = json.JSONDecoder(), 0, []
    text = text or ""
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return out
        value, i = decoder.raw_decode(text, i)
        if isinstance(value, dict):
            out.append(value)
        elif isinstance(value, list):
            out.extend(v for v in value if isinstance(v, dict))


def _listed(answer: dict, *keys: str) -> List[dict]:
    """The rows of a platform list answer, whichever shape it came in."""
    if "text" in answer and len(answer) == 1:
        return json_objects(answer["text"])
    for key in keys:
        if isinstance(answer.get(key), list):
            return [r for r in answer[key] if isinstance(r, dict)]
    if "value" in answer and isinstance(answer["value"], list):
        return [r for r in answer["value"] if isinstance(r, dict)]
    # One object on its own is one row.
    return [answer] if answer else []


# ---- recording a send ----------------------------------------------------

def record(session: Session, *, kind: str, mobile: str, outcome: dict,
           csp_id: Optional[str] = None, csp_name: Optional[str] = None,
           data_request_id=None, processing_job_id=None,
           is_test: bool = False) -> Optional[WhatsAppMessage]:
    """Put one send on the record. The caller commits.

    `outcome` is what whatsapp_platform.send returned. Never raises: a
    message that went out must not be undone because recording it failed.
    The failure is logged with its traceback instead.
    """
    from app.services import whatsapp_platform as wa

    try:
        with session.begin_nested():
            row = WhatsAppMessage(
                csp_id=csp_id, csp_name=(csp_name or None),
                phone=wa.phone_for_whatsapp(mobile) or (mobile or "")[:20],
                kind=kind if kind in KINDS else KIND_OTHER,
                is_test=is_test,
                data_request_id=data_request_id,
                processing_job_id=processing_job_id,
                send_status=outcome.get("status") or SEND_FAILED,
                send_error=(outcome.get("reason") or None),
                job_id=outcome.get("job_id") or None,
                template_name=outcome.get("template_name"),
                sent_at=_now(),
            )
            session.add(row)
            session.flush()
        return row
    except Exception as e:
        logger.error(
            "message_log.record: could not record a %s WhatsApp for CSP %s "
            "(job %s): %s: %s", kind, csp_id, outcome.get("job_id"),
            type(e).__name__, e, exc_info=True)
        return None


# ---- keeping it current --------------------------------------------------

@telemetry.traced("refresh_whatsapp_messages", "message_log")
def refresh(session: Session, *, platform=None, now: Optional[datetime] = None
            ) -> dict:
    """Bring delivered / read / replied up to date. Never raises."""
    from app.config import get_settings
    from app.services import whatsapp_platform

    wa = platform or whatsapp_platform
    now = now or _now()
    window = timedelta(days=get_settings().whatsapp_status_days)
    summary = {"imported": 0, "checked": 0, "status_changed": 0,
               "responded": 0, "errors": []}

    def failed(step: str, e: Exception):
        logger.error("message_log.refresh: %s failed: %s: %s", step,
                     type(e).__name__, e, exc_info=True)
        summary["errors"].append(f"{step}: {type(e).__name__}: {e}")

    try:
        summary["imported"] = _import_history(session, wa)
        session.commit()
    except Exception as e:
        session.rollback()
        failed("reading the platform's send history", e)

    try:
        checked, changed = _check_delivery(session, wa, now, window)
        summary["checked"], summary["status_changed"] = checked, changed
        session.commit()
    except Exception as e:
        session.rollback()
        failed("checking delivery status", e)

    try:
        summary["responded"] += _match_forms(session)
        session.commit()
    except Exception as e:
        session.rollback()
        failed("matching filled-in forms", e)

    try:
        summary["responded"] += _match_replies(session, wa, now, window)
        session.commit()
    except Exception as e:
        session.rollback()
        failed("reading WhatsApp replies", e)

    logger.info("message_log.refresh: %s", summary)
    return summary


def _import_history(session: Session, wa) -> int:
    """This app's sends the platform knows about and the record does not."""
    from app.models.csp_record import CSPRecord

    rows = _listed(wa.call_tool("get_send_history", {}), "history", "rows",
                   "sends", "jobs")
    ours = []
    for row in rows:
        parsed = parse_source(row.get("sheet_name") or row.get("source_name"))
        if parsed and row.get("job_id"):
            ours.append((row, *parsed))
    if not ours:
        return 0

    known = set(session.execute(
        select(WhatsAppMessage.job_id).where(
            WhatsAppMessage.job_id.in_([r["job_id"] for r, *_ in ours]))
    ).scalars().all())
    codes = {csp_id for _, _, csp_id, _ in ours}
    # Scoped to this workspace: a CSP another customer holds is not ours
    # to record, even though the platform's history is shared.
    records = {r.csp_id: r for r in session.execute(
        select(CSPRecord).where(CSPRecord.csp_id.in_(codes))).scalars().all()}

    added = 0
    for row, kind, csp_id, is_test in ours:
        if row["job_id"] in known or csp_id not in records:
            continue
        csp = records[csp_id]
        sent = int(row.get("sent") or 0)
        status = SEND_SENT if sent >= 1 else SEND_FAILED
        session.add(WhatsAppMessage(
            csp_id=csp_id, csp_name=csp.name or None,
            phone=wa.phone_for_whatsapp(csp.mobile or "") or "",
            kind=kind, is_test=is_test, source="history",
            send_status=status,
            send_error=None if status == SEND_SENT else (
                "the WhatsApp platform could not send it "
                f"(failed {row.get('failed', 0)}, skipped "
                f"{row.get('skipped', 0)}; it gave no reason)"),
            job_id=row["job_id"], template_name=row.get("template_name"),
            sent_at=_parse_time(row.get("timestamp")) or _now(),
        ))
        known.add(row["job_id"])
        added += 1
    session.flush()
    return added


def _check_delivery(session: Session, wa, now: datetime, window: timedelta):
    """Meta's delivered / read / failed for each recent send not settled."""
    due = session.execute(
        select(WhatsAppMessage).where(
            WhatsAppMessage.job_id.is_not(None),
            WhatsAppMessage.send_status.in_((SEND_SENT, SEND_FAILED)),
            WhatsAppMessage.sent_at >= now - window,
            (WhatsAppMessage.delivery_status.is_(None))
            | WhatsAppMessage.delivery_status.in_(
                (DELIVERY_SENT, DELIVERY_DELIVERED)),
        ).order_by(WhatsAppMessage.checked_at.asc().nulls_first())
        .limit(MAX_CHECKS_PER_REFRESH)
    ).scalars().all()

    checked = changed = 0
    for message in due:
        message.checked_at = now
        try:
            answer = wa.delivery_status(message.job_id)
        except Exception as e:
            # Kept on the message, logged, and the next one is tried: one
            # job the platform cannot find must not stop the rest.
            message.check_error = f"{type(e).__name__}: {e}"[:2000]
            logger.warning("message_log: status of job %s failed: %s",
                           message.job_id, message.check_error,
                           exc_info=True)
            continue
        checked += 1
        message.check_error = None
        if _apply_delivery(message, answer):
            changed += 1
    session.flush()
    return checked, changed


def _apply_delivery(message: WhatsAppMessage, answer: dict) -> bool:
    """Copy one get_delivery_status answer onto the message."""
    rows = [r for r in (answer.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return False
    row = rows[0]
    before = (message.send_status, message.delivery_status)

    if not message.phone and row.get("phone"):
        message.phone = str(row["phone"])[:20]
    if str(row.get("sent_status", "")).lower() == "failed":
        message.send_status = SEND_FAILED
        message.send_error = message.send_error or (
            "the WhatsApp platform could not send it (it gave no reason)")
        message.delivery_status = DELIVERY_FAILED
        message.delivery_error = row.get("delivery_error") or None
    else:
        status = str(row.get("delivery_status") or "").lower()
        if status in (DELIVERY_SENT, DELIVERY_DELIVERED, DELIVERY_READ,
                      DELIVERY_FAILED):
            message.delivery_status = status
            message.delivery_error = row.get("delivery_error") or None
    message.delivery_updated_at = (_parse_time(row.get("delivery_updated_at"))
                                   or message.delivery_updated_at)
    return (message.send_status, message.delivery_status) != before


def _match_forms(session: Session) -> int:
    """A details message is answered when its form was filled in."""
    from app.models.data_request import ANSWERED, DataRequest

    pairs = session.execute(
        select(WhatsAppMessage, DataRequest)
        .join(DataRequest, DataRequest.id == WhatsAppMessage.data_request_id)
        .where(DataRequest.status == ANSWERED,
               (WhatsAppMessage.response_kind.is_(None))
               | (WhatsAppMessage.response_kind != RESPONSE_FORM))
    ).all()
    for message, request in pairs:
        # The form is the answer that matters, so it replaces a WhatsApp
        # reply such as "ok" that came first.
        message.response_kind = RESPONSE_FORM
        message.responded_at = request.answered_at
        message.response_text = None
    session.flush()
    return len(pairs)


def _match_replies(session: Session, wa, now: datetime,
                   window: timedelta) -> int:
    """A reply on WhatsApp answers the latest message sent to that number."""
    messages = session.execute(
        select(WhatsAppMessage).where(
            WhatsAppMessage.send_status == SEND_SENT,
            WhatsAppMessage.phone != "",
            WhatsAppMessage.sent_at >= now - window,
        ).order_by(WhatsAppMessage.sent_at)
    ).scalars().all()
    if not messages:
        return 0
    by_phone: Dict[str, List[WhatsAppMessage]] = {}
    for m in messages:
        by_phone.setdefault(m.phone, []).append(m)

    replies = _listed(wa.call_tool("get_incoming_messages", {}),
                      "messages", "rows")
    matched = 0
    for reply in sorted(replies, key=lambda r: str(r.get("sent_at") or "")):
        phone = re.sub(r"\D", "", str(reply.get("from_phone") or ""))
        at = _parse_time(reply.get("sent_at"))
        if phone not in by_phone or at is None:
            continue
        answered = [m for m in by_phone[phone] if m.sent_at <= at]
        if not answered:
            continue
        message = answered[-1]
        if message.responded_at is not None:
            continue
        message.responded_at = at
        message.response_kind = RESPONSE_WHATSAPP
        message.response_text = (str(reply.get("body") or "")
                                 or f"({reply.get('msg_type') or 'reply'})")[:500]
        matched += 1
    session.flush()
    return matched


# ---- what the screen shows -----------------------------------------------

# One word per message for where it got to, in the order of the screen.
NOT_SENT = "not_sent"          # rejected, failed, or waiting for approval
NOT_RECEIVED = "not_received"  # WhatsApp could not get it to the phone
SENT = "sent"                  # left, not confirmed on the phone yet
DELIVERED = "delivered"        # on the phone, not opened
READ = "read"

STAGES = (NOT_SENT, NOT_RECEIVED, SENT, DELIVERED, READ)


def stage(message: WhatsAppMessage, now: Optional[datetime] = None) -> str:
    now = now or _now()
    if message.send_status != SEND_SENT:
        return NOT_SENT
    if message.delivery_status == DELIVERY_FAILED:
        return NOT_RECEIVED
    if message.delivery_status == DELIVERY_READ:
        return READ
    if message.delivery_status == DELIVERY_DELIVERED:
        return DELIVERED
    if message.sent_at and now - message.sent_at > NOT_RECEIVED_AFTER:
        return NOT_RECEIVED
    return SENT


def why(message: WhatsAppMessage, now: Optional[datetime] = None) -> str:
    """A plain reason for a message that did not get through."""
    s = stage(message, now)
    if s == NOT_SENT:
        if message.send_status == SEND_PENDING:
            return "Not sent — the wording is waiting for Meta's approval"
        if message.send_status == SEND_REJECTED:
            return "Rejected — " + (message.send_error or "Meta refused it")
        return "Not sent — " + (message.send_error or "no reason given")
    if s == NOT_RECEIVED:
        if message.delivery_status == DELIVERY_FAILED:
            return "Did not reach the phone — " + (
                message.delivery_error or "WhatsApp gave no reason")
        return ("Not on the phone after 24 hours — phone off, not on "
                "WhatsApp, or a wrong number")
    return ""


def summarise(messages: Iterable[WhatsAppMessage],
              now: Optional[datetime] = None) -> Dict[str, dict]:
    """Counts per kind. 'responded'/'not_responded' are of those that left."""
    now = now or _now()
    out = {k: {"total": 0, **{s: 0 for s in STAGES},
               "responded": 0, "not_responded": 0}
           for k in (KIND_DATA_REQUEST, KIND_MISSING_DATA,
                     KIND_DOCUMENTS_READY)}
    for m in messages:
        if m.kind not in out:
            continue
        counts = out[m.kind]
        counts["total"] += 1
        s = stage(m, now)
        counts[s] += 1
        if s != NOT_SENT:
            counts["responded" if m.responded_at else "not_responded"] += 1
    return out


def as_row(m: WhatsAppMessage, now: Optional[datetime] = None) -> dict:
    s = stage(m, now)
    return {
        "id": str(m.id),
        "kind": m.kind,
        "csp_id": m.csp_id,
        "csp_name": m.csp_name,
        "phone": m.phone,
        "is_test": m.is_test,
        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
        "stage": s,
        "reason": why(m, now),
        "delivery_updated_at": (m.delivery_updated_at.isoformat()
                                if m.delivery_updated_at else None),
        "responded": m.responded_at is not None if s != NOT_SENT else None,
        "responded_at": m.responded_at.isoformat() if m.responded_at else None,
        "response_kind": m.response_kind,
        "response_text": m.response_text,
        "job_id": m.job_id,
        "check_error": m.check_error,
        "source": m.source,
    }
