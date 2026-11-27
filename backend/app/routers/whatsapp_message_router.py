"""
CSP DocMaker — the WhatsApp messages screen (tracker No. 110)

For Admins and Super Admins: for the details-verification, details-missing
and documents-sent messages, who was sent one, whose was rejected or never
arrived, who read it, and who answered. Read-only, apart from Refresh, which
fetches the latest status from Eko's WhatsApp platform straight away instead
of waiting for the next scheduled check.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.whatsapp_message import KINDS, WhatsAppMessage
from app.services import message_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/whatsapp-messages",
                   tags=["admin", "messaging"])

MAX_ROWS = 2000


@router.get("")
async def report(
    kind: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    responded: Optional[bool] = Query(None),
    days: int = Query(30, ge=0, le=3650,
                      description="0 = every message ever recorded"),
    include_tests: bool = Query(True),
    q: Optional[str] = Query(None, max_length=100),
    because: Optional[str] = Query(None, max_length=40),
    date_from: Optional[str] = Query(
        None, description="India day, YYYY-MM-DD, inclusive (No. 272)"),
    date_to: Optional[str] = Query(
        None, description="India day, YYYY-MM-DD, inclusive (No. 272)"),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """The counts for each message, and the messages themselves.

    date_from / date_to (No. 272): only messages sent on those India days -
    the counts too. When either is given it takes the place of `days`."""
    from app.services import india_days

    if kind and kind not in KINDS:
        raise HTTPException(400, f"Unknown message kind {kind!r}.")
    if stage and stage not in message_log.STAGES:
        raise HTTPException(400, f"Unknown status {stage!r}.")
    sent_on = india_days.http_bounds(date_from, date_to)

    now = datetime.now(timezone.utc)
    query = select(WhatsAppMessage)
    if india_days.asked(sent_on):
        query = india_days.where(query, WhatsAppMessage.sent_at, sent_on)
    elif days:
        query = query.where(WhatsAppMessage.sent_at >= now - timedelta(days=days))
    if not include_tests:
        query = query.where(WhatsAppMessage.is_test.is_(False))
    if q and q.strip():
        # Matched as every search box matches (search_match, No. 175):
        # capitals and extra spaces ignored, a phone by its digits, and the
        # words a person sent.
        from app.services import search_match
        term = search_match.normalize(q)
        like = f"%{term}%"
        digits = "".join(ch for ch in term if ch.isdigit())
        condition = (
            func.lower(func.coalesce(WhatsAppMessage.csp_id, "")).like(like)
            | func.lower(func.regexp_replace(
                func.coalesce(WhatsAppMessage.csp_name, ""), r"\s+", " ", "g")).like(like)
            | func.lower(func.coalesce(WhatsAppMessage.body_text, "")).like(like))
        if len(digits) >= 3:
            condition = condition | WhatsAppMessage.phone.like(f"%{digits}%")
        query = query.where(condition)
    messages = (await session.execute(
        query.order_by(WhatsAppMessage.sent_at.desc())
    )).scalars().all()

    summary = message_log.summarise(messages, now)

    def wanted(m) -> bool:
        if kind and m.kind != kind:
            return False
        if because and m.sent_because != because:
            return False
        s = message_log.stage(m, now)
        if stage and s != stage:
            return False
        if responded is not None:
            if s == message_log.NOT_SENT:
                return False
            if (m.responded_at is not None) != responded:
                return False
        return True

    rows = [message_log.as_row(m, now) for m in messages if wanted(m)]
    # No. 194: who sent each one — the app (automatic), you, or which RM /
    # Admin — with their name from the access list.
    me = (user.get("sub") or user.get("email") or "").lower()
    names = await _names(session, {m.sent_by for m in messages if m.sent_by})
    for row in rows:
        row.update(_sender(row.get("sent_by"), row.get("sent_because"), me, names))
    senders: dict = {}
    for m in messages:
        who = _sender(m.sent_by, m.sent_because, me, names)
        entry = senders.setdefault(who["sender_key"], {
            "key": who["sender_key"], "label": who["sender_label"],
            "role": who["sender_role"], "me": who["sender_key"] == me,
            "count": 0})
        entry["count"] += 1
    last_checked = (await session.execute(
        select(func.max(WhatsAppMessage.checked_at)))).scalar()
    # Why messages were sent, other than the usual flow (No. 156).
    from app.services import send_reason
    reasons = {}
    for m in messages:
        if m.sent_because:
            reasons[m.sent_because] = reasons.get(m.sent_because, 0) + 1
    return {
        "summary": summary,
        # Automatic first, then you, then everyone else by how many (No. 194).
        "senders": sorted(senders.values(), key=lambda e: (
            e["key"] != AUTOMATIC, not e["me"], -e["count"])),
        "sent_because": [{"key": k, "label": send_reason.label(k), "count": n}
                         for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])],
        "contact_fixes": await session.run_sync(_contact_status),
        # The feedback question's answers: 1 / 2 / 3 (No. 160).
        "feedback_answers": await session.run_sync(_feedback_answers),
        "rows": rows[:MAX_ROWS],
        "total_rows": len(rows),
        "truncated": len(rows) > MAX_ROWS,
        "last_checked_at": last_checked.isoformat() if last_checked else None,
        "status_days": _settings().whatsapp_status_days,
    }


AUTOMATIC = "automatic"
UNRECORDED = "person"


async def _names(session: AsyncSession, emails: set) -> dict:
    """email -> (name, role) from the access list, for the people who sent."""
    if not emails:
        return {}
    from app.models.authorization_record import AuthorizationRecord
    rows = (await session.execute(select(AuthorizationRecord).where(
        func.lower(AuthorizationRecord.email).in_([e.lower() for e in emails])
    ))).scalars().all()
    return {r.email.lower(): (r.name, getattr(r.role, "value", str(r.role)))
            for r in rows}


def _sender(sent_by, sent_because, me: str, names: dict) -> dict:
    """How the WhatsApp messages screen names who sent a message (No. 194):
    Automatic (the app), You, or the person by name (and role)."""
    from app.services import send_reason
    person = (sent_by or "").lower()
    if person:
        name, role = names.get(person, (person, ""))
        label = "You" if person == me else name
        return {"sender_key": person, "sender_label": label,
                "sender_role": role}
    if sent_because == send_reason.MANUAL:
        # Sent by hand before the sender was recorded (before No. 194).
        return {"sender_key": UNRECORDED,
                "sender_label": "A person (who was not recorded)",
                "sender_role": ""}
    return {"sender_key": AUTOMATIC, "sender_label": "Automatic",
            "sender_role": ""}


@router.get("/{message_id}")
async def one_message(
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """One message opened: its journey, and what the CSP changed (No. 111)."""
    message = (await session.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.id == message_id)
    )).scalars().first()
    if message is None:
        raise HTTPException(404, "No such message.")
    return await session.run_sync(
        lambda sync: message_log.details(sync, message))


@router.get("/{message_id}/conversation")
async def conversation(
    message_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """The WhatsApp chat with this CSP from this message on (No. 112).

    Read live from Eko's WhatsApp platform. If it cannot be reached the
    answer says so (with the reason) instead of showing an empty chat,
    which would look like the CSP had not replied.
    """
    from app.services import whatsapp_platform as wa

    message = (await session.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.id == message_id)
    )).scalars().first()
    if message is None:
        raise HTTPException(404, "No such message.")
    if not message.phone:
        return {"phone": "", "items": [], "error": "No mobile number is "
                "known for this message, so there is no chat to show."}
    ours = (await session.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.phone == message.phone)
        .order_by(WhatsAppMessage.sent_at)
    )).scalars().all()
    try:
        replies = await asyncio.to_thread(
            message_log.replies_from, wa, message.phone)
    except Exception as e:
        logger.error("whatsapp_messages.conversation: inbox for message %s "
                     "could not be read: %s: %s", message_id,
                     type(e).__name__, e, exc_info=True)
        return {"phone": message.phone, "items": [],
                "error": f"The WhatsApp platform could not be read: "
                         f"{type(e).__name__}: {e}"}
    return {"phone": message.phone,
            "items": message_log.build_conversation(
                list(ours), replies, message.sent_at),
            "error": None}


@router.get("/csp/{csp_id}/conversation")
async def csp_conversation(
    csp_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """One CSP's whole WhatsApp chat, opened from their name (No. 171).

    Every number the app messaged for this CSP, oldest message first, with
    what they wrote back (read live from Eko's WhatsApp platform; a failure
    is shown, not hidden).
    """
    return await chat_for_csp(session, csp_id)


async def chat_for_csp(session: AsyncSession, csp_id: str) -> dict:
    """The chat itself; also opened by an RM from Action Required (No. 174),
    after csp_router has checked the RM may see this CSP."""
    from app.models.csp_record import CSPRecord
    from app.models.csp_reply import CspReply
    from app.services import whatsapp_platform as wa

    record = (await session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == csp_id))).scalars().first()
    ours = (await session.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.csp_id == csp_id)
        .order_by(WhatsAppMessage.sent_at))).scalars().all()
    phones = {m.phone for m in ours if m.phone}
    phones |= set((await session.execute(select(CspReply.phone).where(
        CspReply.csp_id == csp_id))).scalars())
    phones.discard(None)
    phones.discard("")
    out = {"csp_id": csp_id, "csp_name": record.name if record else "",
           "phones": sorted(phones), "items": [], "error": None}
    if record is None and not ours:
        raise HTTPException(404, "No such CSP.")
    if not phones:
        out["error"] = ("No WhatsApp has been sent to this CSP, so there is "
                        "no chat to show.")
        return out
    replies = []
    try:
        for phone in sorted(phones):
            replies += await asyncio.to_thread(message_log.replies_from, wa,
                                               phone)
    except Exception as e:
        logger.error("whatsapp_messages.csp_conversation: inbox for %s could "
                     "not be read: %s: %s", csp_id, type(e).__name__, e,
                     exc_info=True)
        out["error"] = (f"The WhatsApp platform could not be read: "
                        f"{type(e).__name__}: {e}")
    # The whole chat: everything they wrote, even before our first message
    # on record (the platform's inbox may hold older ones).
    since = datetime(2000, 1, 1, tzinfo=timezone.utc)
    out["items"] = message_log.build_conversation(list(ours), replies, since)
    return out


@router.post("/refresh")
async def refresh(
    user=Depends(require_role("admin", "super_admin")),
):
    """Fetch delivered / read / replied from the platform now.

    Runs in a thread with its own connection: it waits on the platform, and
    must not hold up every other request while it does. The workspace in
    force travels with it (asyncio.to_thread copies the context).
    """
    summary = await asyncio.to_thread(_refresh_now)
    if summary["errors"]:
        logger.warning("whatsapp_messages.refresh by %s: %s",
                       (user or {}).get("email"), summary["errors"])
    return summary


def _refresh_now() -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            return message_log.refresh(session)
    finally:
        engine.dispose()


def _settings():
    from app.config import get_settings
    return get_settings()


def _contact_status(sync_session):
    from app.services import feedback_loops
    return feedback_loops.contact_status(sync_session)


def _feedback_answers(sync_session):
    from app.services import documents_feedback
    out = documents_feedback.summary(sync_session, limit=0)
    return {"answers": out["answers"], "no_answer": out["no_answer"]}
