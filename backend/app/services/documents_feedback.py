"""
CSP DocMaker — "did you get your documents?" (No. 152)

Asked 27 Oct 2026: after the documents message, ask the CSP whether they got
their documents and whether they like them. Decided: reply 1 / 2 / 3 —
15 minutes after the documents message (No. 159; it was the next day,
DOCUMENTS_FEEDBACK_AFTER_MINUTES):

  1 — got them and everything is correct  -> "thank you"
  2 — did not get them                    -> the documents email again
  3 — something is wrong in them          -> the data verification message

The question goes DOCUMENTS_FEEDBACK_AFTER_MINUTES (15) after the
"documents ready" WhatsApp (not after 7 days), once per documents message and at most once a
week per CSP, 8 am - 8 pm, never to a CSP on hold or whose documents
message did not reach the phone (the contact loop deals with that). The
answer is read by the reply agent (services/csp_replies.py), which writes
the reply and, when it is sent, does what the answer needs.

Off with DOCUMENTS_FEEDBACK_ENABLED=false. Deterministic; no AI.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import func, select

from app.models.feedback_loop import CspFeedback

logger = logging.getLogger(__name__)

KIND = "feedback"
def _wait() -> timedelta:
    """How long after the documents message the question goes (No. 159:
    15 minutes — was the next day)."""
    from app.config import get_settings
    return timedelta(minutes=max(get_settings().documents_feedback_after_minutes, 1))
TOO_LATE = timedelta(days=7)
ONCE_PER = timedelta(days=7)
MAX_TRIES = 3
BATCH = 20

# The WhatsApp wording (Meta approves it once; keep it stable).
WORDING = ("Namaste {name}, humne abhi aapke CSP documents aapke email par "
           "bheje hain. Kya aapko mil gaye? Reply karein: 1 - mil gaye aur sab "
           "sahi hai, 2 - nahi mile, 3 - kuch galat hai. Dhanyavaad, Eko "
           "Bharat Ventures.")

ANSWERS = {"1": "Got them, all correct", "2": "Did not get them",
           "3": "Something is wrong"}


def parse_answer(text: str) -> Optional[str]:
    """'1', '2', '3' from a reply to the feedback question, or None."""
    from app.services.csp_replies import norm
    t = norm(text)
    m = re.match(r"^([123])(\s|$)", t)
    if m:
        return m.group(1)
    if re.search(r"(nahi|nahin|nhi|not|na)\s*(mile|mila|mili|received|aaye|aaya)"
                 r"|didn t get|did not get|नहीं मिल", t):
        return "2"
    if re.search(r"(galat|wrong|mistake|error|गलत)", t):
        return "3"
    if re.search(r"(mil gaye|mil gaya|mil gyi|mil gaye|received|got (it|them)|"
                 r"sab sahi|sahi hai|मिल गए|मिल गया)", t):
        return "1"
    return None


def open_question(session, csp_id: str, now: Optional[datetime] = None):
    """The feedback question this CSP has not answered yet, if any."""
    now = now or datetime.now(timezone.utc)
    return session.execute(
        select(CspFeedback).where(CspFeedback.csp_id == csp_id,
                                  CspFeedback.ask_status == "sent",
                                  CspFeedback.answer.is_(None),
                                  CspFeedback.asked_at >= now - TOO_LATE)
        .order_by(CspFeedback.asked_at.desc())).scalars().first()


def _due(session, now: datetime):
    """Documents messages whose feedback question is due (or to retry)."""
    from app.models.whatsapp_message import (KIND_DOCUMENTS_READY, SEND_SENT,
                                             WhatsAppMessage)
    from app.services import message_log

    done = {f.documents_message_id: f for f in
            session.execute(select(CspFeedback)).scalars()}
    asked_lately = {csp for (csp,) in session.execute(
        select(CspFeedback.csp_id).where(
            CspFeedback.asked_at >= now - ONCE_PER,
            CspFeedback.ask_status == "sent"))}
    messages = session.execute(
        select(WhatsAppMessage).where(
            WhatsAppMessage.kind == KIND_DOCUMENTS_READY,
            WhatsAppMessage.send_status == SEND_SENT,
            WhatsAppMessage.is_test.is_(False),
            WhatsAppMessage.csp_id.isnot(None),
            WhatsAppMessage.sent_at <= now - _wait(),
            WhatsAppMessage.sent_at >= now - TOO_LATE)
        .order_by(WhatsAppMessage.sent_at)).scalars().all()
    for m in messages:
        row = done.get(m.id)
        if row is not None and not (row.ask_status == "pending"
                                    and row.tries < MAX_TRIES):
            continue
        if m.csp_id in asked_lately:
            continue
        if message_log.stage(m, now) == message_log.NOT_RECEIVED:
            continue            # the contact loop's business
        yield m, row


def run(session, now: Optional[datetime] = None, wa=None) -> Dict[str, int]:
    """Send the feedback questions that are due (the caller checks hours)."""
    from app.config import get_settings
    from app.models.csp_record import CSPRecord
    from app.services import message_log, whatsapp_platform

    if not get_settings().documents_feedback_enabled:
        return {"skipped": "off (DOCUMENTS_FEEDBACK_ENABLED=false)"}
    wa = wa or whatsapp_platform
    now = now or datetime.now(timezone.utc)
    counts = {"asked": 0, "pending": 0, "failed": 0}
    for message, row in list(_due(session, now))[:BATCH]:
        record = session.execute(select(CSPRecord).where(
            CSPRecord.csp_id == message.csp_id)).scalar_one_or_none()
        if record is None or record.send_hold:
            continue
        if row is None:
            row = CspFeedback(csp_id=record.csp_id, phone=message.phone,
                              documents_message_id=message.id)
            session.add(row)
        outcome = wa.send(message.phone, WORDING,
                          {"name": record.name or "CSP"},
                          source_name=message_log.source_name(KIND, record.csp_id))
        message_log.record(session, kind=KIND, mobile=message.phone,
                           outcome=outcome, csp_id=record.csp_id,
                           csp_name=record.name or "")
        row.tries += 1
        if outcome["status"] == wa.SENT:
            row.ask_status, row.asked_at, row.note = "sent", now, ""
            counts["asked"] += 1
        elif outcome["status"] == wa.PENDING:
            row.ask_status = "pending"
            row.note = "waiting for Meta to approve the wording (first time)"
            counts["pending"] += 1
        else:
            row.ask_status = "pending" if row.tries < MAX_TRIES else "failed"
            row.note = f"not sent: {outcome.get('reason', '')}"[:500]
            counts["failed"] += 1
        session.commit()
    if counts["asked"]:
        logger.info("documents_feedback: asked %d CSP(s)", counts["asked"])
    return counts


def summary(session, limit: int = 100) -> dict:
    from app.models.csp_record import CSPRecord
    rows = session.execute(
        select(CspFeedback, CSPRecord.name)
        .outerjoin(CSPRecord, CSPRecord.csp_id == CspFeedback.csp_id)
        .order_by(CspFeedback.updated_at.desc()).limit(limit)).all()
    counts = dict(session.execute(
        select(CspFeedback.answer, func.count())
        .where(CspFeedback.ask_status == "sent")
        .group_by(CspFeedback.answer)).all())
    return {
        "asked": sum(counts.values()),
        "answers": {k: counts.get(k, 0) for k in ANSWERS},
        "no_answer": counts.get(None, 0),
        "rows": [{
            "csp_id": f.csp_id,
            "csp_name": name or "",
            "ask_status": f.ask_status,
            "asked_at": f.asked_at.isoformat() if f.asked_at else None,
            "answer": f.answer,
            "answer_label": ANSWERS.get(f.answer or "", ""),
            "answer_text": f.answer_text,
            "answered_at": f.answered_at.isoformat() if f.answered_at else None,
            "note": f.note,
        } for f, name in rows],
    }
