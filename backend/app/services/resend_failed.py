"""
CSP DocMaker — a WhatsApp that failed is sent again until it goes (No. 164)

Asked 28 Oct 2026: "you will have to deliver the message until sent, in
any error other than when the number does not exist on WhatsApp". A send
the WhatsApp platform failed (platform unreachable, Meta unreachable, the
wording waiting for Meta's approval, ...) is tried again, with a longer
wait each time — 30 minutes, 1 hour, 2 hours, then every 4 hours — until it
is sent or WINDOW (7 days) has passed.

Not sent again here:

  * a number that is not on WhatsApp — the contact loop's (alternate
    number, then email; services/feedback_loops.py);
  * a wording Meta refused — a person changes the wording;
  * a details message the job that sent it already tries again: a new CSP
    still waiting to be finished (new_csp_worker) and an old CSP still in
    the verification batch (verify_old_csps_worker) — two jobs trying the
    same CSP would message them twice;
  * a CSP the contact loop is working on, or one on hold;
  * a details message for a CSP who has filled in the form since.

What is sent again: the details message (data verification / details
still needed), the "documents ready" message, and a reply to a CSP that
failed. The feedback question is tried again by services/documents_feedback
with the same waits. Every message sent again says so on the WhatsApp
messages screen ("Sent again after an error", send_reason.RETRY).

Deterministic; no AI (AI_SPEC D1).
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Set, Tuple

from sqlalchemy import func, or_, select

logger = logging.getLogger(__name__)

WINDOW = timedelta(days=7)
FIRST_WAIT = timedelta(minutes=30)
LONGEST_WAIT = timedelta(hours=4)

# The number is not on WhatsApp (or not a number at all): the contact
# loop's business, not something a second try fixes.
NOT_ON_WHATSAPP = re.compile(
    r"not a usable mobile number|131026|not (a )?valid whatsapp|"
    r"not on whatsapp|not a whatsapp|incapable of receiving|"
    r"invalid (phone|mobile|number|recipient)|undeliverable", re.I)

# A reason a try did not happen that will pass by itself: try again later.
# Any other reason (already asked, nothing missing, on hold, ...) means the
# message is not needed any more.
WAITING = re.compile(r"^waiting:|tried again|no active|public address|"
                     r"publicly reachable", re.I)

DETAILS, DOCUMENTS = "details", "documents"


def not_on_whatsapp(reason: Optional[str]) -> bool:
    return bool(reason) and NOT_ON_WHATSAPP.search(reason) is not None


def wait(tries: int) -> timedelta:
    """How long after the last failed try the next one goes."""
    return min(FIRST_WAIT * (2 ** max(tries - 1, 0)), LONGEST_WAIT)


def _groups():
    from app.models.whatsapp_message import (KIND_DATA_REQUEST,
                                             KIND_DOCUMENTS_READY,
                                             KIND_MISSING_DATA)
    return {KIND_DATA_REQUEST: DETAILS, KIND_MISSING_DATA: DETAILS,
            KIND_DOCUMENTS_READY: DOCUMENTS}


def _owned(session, settings) -> Set[str]:
    """CSPs whose details message the job that sent it tries again itself."""
    from app.models.csp_record import CSPRecord
    owned = set(session.execute(select(CSPRecord.csp_id).where(
        or_(CSPRecord.origin == "new", CSPRecord.auto_enrolled_at.is_not(None)),
        CSPRecord.new_csp_processed_at.is_(None))).scalars())
    if settings.verify_old_csps_enabled and settings.calling_sheet_id:
        from app.workers.verify_old_csps_worker import to_verify
        owned |= {c.csp_id for c in to_verify(session, 1_000_000)}
    return owned


def _fixing(session) -> Set[str]:
    """CSPs the contact loop is working on."""
    from app.models.feedback_loop import ContactFix
    return set(session.execute(select(ContactFix.csp_id).where(
        ContactFix.status.in_(("open", "asked", "corrected",
                               "trying_alternate")))).scalars())


def due(session, settings, now: datetime):
    """(message, tries) for each failed message whose next try is due —
    the newest message of each CSP's details / documents messages."""
    from app.models.whatsapp_message import SEND_REJECTED, WhatsAppMessage
    from app.services import message_log

    groups = _groups()
    chains: Dict[Tuple[str, str], list] = {}
    for m in session.execute(
            select(WhatsAppMessage).where(
                WhatsAppMessage.kind.in_(list(groups)),
                WhatsAppMessage.is_test.is_(False),
                WhatsAppMessage.csp_id.isnot(None),
                WhatsAppMessage.sent_at >= now - WINDOW)
            .order_by(WhatsAppMessage.sent_at)).scalars():
        chains.setdefault((m.csp_id, groups[m.kind]), []).append(m)
    owned = fixing = None
    for (csp_id, group), messages in chains.items():
        last = messages[-1]
        if (message_log.stage(last, now) != message_log.NOT_SENT
                or last.send_status == SEND_REJECTED
                or last.retry_status
                or not_on_whatsapp(last.send_error)):
            continue
        tries = 0
        for m in reversed(messages):
            if message_log.stage(m, now) != message_log.NOT_SENT:
                break
            tries += 1
        since = max(last.sent_at, last.retried_at or last.sent_at)
        if now - since < wait(tries):
            continue
        if fixing is None:
            owned, fixing = _owned(session, settings), _fixing(session)
        if csp_id in fixing or (group == DETAILS and csp_id in owned):
            continue
        yield last, tries


def _details(session, message, record) -> Tuple[Optional[bool], str]:
    from app.models.data_request import ANSWERED, DataRequest
    from app.models.whatsapp_message import KIND_DATA_REQUEST
    from app.services import message_sender, send_reason

    answered = session.execute(select(func.count()).select_from(DataRequest).where(
        DataRequest.csp_id == record.csp_id, DataRequest.status == ANSWERED,
        DataRequest.answered_at >= message.sent_at)).scalar()
    if answered:
        return None, "not needed: they filled in the form since"
    try:
        channel = message_sender.choose_channel(session, kind="whatsapp")
    except message_sender.NoChannel:
        return None, "waiting: no active WhatsApp channel"
    mobile = (message.phone if message.sent_because == send_reason.ALTERNATE_NUMBER
              else None)
    out = message_sender.ask_for_details(
        session, record, channel=channel,
        verify=message.kind == KIND_DATA_REQUEST, mobile=mobile)
    if out.get("sent"):
        return True, "sent"
    reason = out.get("reason") or "not sent"
    if "via" in out:
        return False, reason
    return None, reason if WAITING.search(reason) else f"not needed: {reason}"


def _documents(session, message, record) -> Tuple[Optional[bool], str]:
    from app.services import feedback_loops, send_reason
    mobile = (message.phone if message.sent_because == send_reason.ALTERNATE_NUMBER
              else None)
    ok, note, resent = feedback_loops._resend_documents_whatsapp(
        session, None, record, mobile=mobile)
    if ok and resent:
        return True, "sent"
    if ok:
        return None, f"not needed: {note}"
    return ok, note


def _due_replies(session, now: datetime):
    """(reply, tries) for each failed reply to a CSP whose next try is due."""
    from app.models.csp_reply import CspReply
    from app.models.whatsapp_message import (KIND_OTHER, SEND_SENT,
                                             WhatsAppMessage)
    for reply in session.execute(select(CspReply).where(
            CspReply.status == "failed",
            CspReply.updated_at >= now - WINDOW)
            .order_by(CspReply.updated_at)).scalars().all():
        if not_on_whatsapp(reply.note):
            continue
        tries = session.execute(select(func.count()).select_from(WhatsAppMessage).where(
            WhatsAppMessage.csp_id == reply.csp_id,
            WhatsAppMessage.kind == KIND_OTHER,
            WhatsAppMessage.send_status != SEND_SENT,
            WhatsAppMessage.sent_at >= reply.created_at)).scalar() or 1
        if now - reply.updated_at >= wait(tries):
            yield reply, tries


def run(session, settings, now: Optional[datetime] = None, wa=None) -> Dict[str, int]:
    """One pass: try again what is due, at most RESEND_FAILED_BATCH sends."""
    from app.models.csp_record import CSPRecord
    from app.models.whatsapp_message import KIND_DOCUMENTS_READY
    from app.services import csp_replies, send_reason

    now = now or datetime.now(timezone.utc)
    budget = max(int(settings.resend_failed_batch), 0)
    counts = {"sent": 0, "failed": 0, "waiting": 0, "not_needed": 0}

    for message, tries in list(due(session, settings, now)):
        if budget <= 0:
            break
        record = session.execute(select(CSPRecord).where(
            CSPRecord.csp_id == message.csp_id)).scalar_one_or_none()
        if record is None or record.send_hold:
            ok, note = None, ("not needed: the CSP is not in the records"
                              if record is None else f"not needed: {record.send_hold}")
        else:
            try:
                with send_reason.because(send_reason.RETRY):
                    ok, note = (_documents if message.kind == KIND_DOCUMENTS_READY
                                else _details)(session, message, record)
            except Exception as e:
                session.rollback()
                ok, note = False, f"{type(e).__name__}: {e}"[:500]
                logger.error("resend_failed: %s %s for %s failed: %s",
                             message.kind, message.id, message.csp_id, note,
                             exc_info=True)
        message.retried_at, message.retry_note = now, note[:500]
        if ok is None and note.startswith("not needed"):
            message.retry_status = "not_needed"
            counts["not_needed"] += 1
        elif ok is None:
            counts["waiting"] += 1
        else:
            budget -= 1
            counts["sent" if ok else "failed"] += 1
        logger.info("resend_failed: %s for CSP %s (try %d) — %s", message.kind,
                    message.csp_id, tries + 1, note)
        session.commit()

    for reply, tries in list(_due_replies(session, now)):
        if budget <= 0:
            break
        try:
            with send_reason.because(send_reason.RETRY):
                csp_replies.send(session, reply, reply.decided_by or "automatic",
                                 wa=wa)
            budget -= 1
            counts["sent" if reply.status == "sent" else "failed"] += 1
        except ValueError as e:
            reply.status, reply.note = "skipped", str(e)[:500]
            counts["not_needed"] += 1
        logger.info("resend_failed: reply to CSP %s (try %d) — %s",
                    reply.csp_id, tries + 1, reply.status)
        session.commit()

    if any(counts.values()):
        logger.info("resend_failed.run: %s", counts)
    return counts


def summary(session, now: Optional[datetime] = None) -> dict:
    """What was sent again in the last WINDOW, for the harness table."""
    from app.models.whatsapp_message import SEND_SENT, WhatsAppMessage
    from app.services import send_reason
    now = now or datetime.now(timezone.utc)
    rows = dict(session.execute(
        select(WhatsAppMessage.send_status, func.count())
        .where(WhatsAppMessage.sent_because == send_reason.RETRY,
               WhatsAppMessage.sent_at >= now - WINDOW)
        .group_by(WhatsAppMessage.send_status)).all())
    return {"sent": rows.get(SEND_SENT, 0),
            "failed": sum(v for k, v in rows.items() if k != SEND_SENT)}
