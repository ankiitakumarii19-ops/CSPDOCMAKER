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
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """The counts for each message, and the messages themselves."""
    if kind and kind not in KINDS:
        raise HTTPException(400, f"Unknown message kind {kind!r}.")
    if stage and stage not in message_log.STAGES:
        raise HTTPException(400, f"Unknown status {stage!r}.")

    now = datetime.now(timezone.utc)
    query = select(WhatsAppMessage)
    if days:
        query = query.where(WhatsAppMessage.sent_at >= now - timedelta(days=days))
    if not include_tests:
        query = query.where(WhatsAppMessage.is_test.is_(False))
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.where(
            func.lower(func.coalesce(WhatsAppMessage.csp_id, "")).like(like)
            | func.lower(func.coalesce(WhatsAppMessage.csp_name, "")).like(like)
            | WhatsAppMessage.phone.like(like))
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
        "sent_because": [{"key": k, "label": send_reason.label(k), "count": n}
                         for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])],
        "rows": rows[:MAX_ROWS],
        "total_rows": len(rows),
        "truncated": len(rows) > MAX_ROWS,
        "last_checked_at": last_checked.isoformat() if last_checked else None,
        "status_days": _settings().whatsapp_status_days,
    }


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
