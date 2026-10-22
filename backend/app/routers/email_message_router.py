"""
CSP DocMaker — tracking emails sent to CSPs (tracker No. 127)

  GET  /api/public/email-open/{token}.gif   PUBLIC — the 1-pixel picture in
                                            each email; loading it = opened
  GET  /api/admin/email-messages            Admin + Super Admin: counts by
                                            kind and the list
  POST /api/admin/email-messages/refresh    read bounce notices now

What is recorded and how reliable each part is: models/email_message.py.
"""

import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.email_message import (FAILED, KIND_CHAT, KIND_DETAILS,
                                      KIND_DOCUMENTS, KIND_OTHER, SENT,
                                      EmailMessage)

logger = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api/public", tags=["public"])
router = APIRouter(prefix="/api/admin/email-messages", tags=["admin"])

# A transparent 1×1 GIF.
PIXEL = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
TITLES = {KIND_DOCUMENTS: "Documents", KIND_DETAILS: "Details requests",
          KIND_CHAT: "Chat messages", KIND_OTHER: "Other"}
TILES = ("sent", "failed", "bounced", "opened", "not_opened")


@public_router.get("/email-open/{token}.gif")
async def email_opened(token: str, session: AsyncSession = Depends(get_session)):
    """Always answers with the picture; an unknown token changes nothing."""
    from app.workspace_context import all_workspaces
    if len(token) <= 64 and token.isalnum():
        try:
            with all_workspaces():
                row = (await session.execute(select(EmailMessage).where(
                    EmailMessage.track_token == token))).scalars().first()
                if row is not None:
                    now = datetime.now(timezone.utc)
                    row.opened_at = row.opened_at or now
                    row.last_opened_at = now
                    row.open_count = (row.open_count or 0) + 1
                    await session.commit()
        except Exception as e:
            logger.error("email_message_router: could not record an open: "
                         "%s: %s", type(e).__name__, e, exc_info=True)
    return Response(PIXEL, media_type="image/gif", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


def _bucket(m: EmailMessage) -> str:
    if m.send_status == FAILED:
        return "failed"
    if m.bounced_at:
        return "bounced"
    return "opened" if m.opened_at else "not_opened"


def _row(m: EmailMessage) -> dict:
    return {"id": str(m.id), "csp_id": m.csp_id, "csp_name": m.csp_name,
            "to": m.to_email, "kind": m.kind, "subject": m.subject,
            "status": _bucket(m), "sent_at": m.sent_at.isoformat(),
            "error": m.send_error, "opened_at": (m.opened_at.isoformat()
                                                 if m.opened_at else None),
            "open_count": m.open_count,
            "bounced_at": (m.bounced_at.isoformat() if m.bounced_at
                           else None),
            "bounce_reason": m.bounce_reason}


@router.get("")
async def report(kind: Optional[str] = Query(None),
                 status: Optional[str] = Query(None),
                 q: Optional[str] = Query(None, max_length=100),
                 session: AsyncSession = Depends(get_session),
                 user=Depends(require_role("admin", "super_admin"))):
    rows = (await session.execute(select(EmailMessage).order_by(
        EmailMessage.sent_at.desc()))).scalars().all()
    counts = {}
    for k in TITLES:
        mine = [m for m in rows if m.kind == k]
        c = {t: 0 for t in TILES}
        for m in mine:
            c[_bucket(m)] += 1
        c["sent"] = sum(1 for m in mine if m.send_status == SENT)
        counts[k] = {"title": TITLES[k], **c}
    shown = [m for m in rows
             if (not kind or m.kind == kind)
             and (not status or (status == "sent" and m.send_status == SENT)
                  or _bucket(m) == status)
             and (not q or q.lower() in " ".join(
                 filter(None, [m.csp_id, m.csp_name, m.to_email])).lower())]
    return {"counts": counts, "total": len(shown),
            "messages": [_row(m) for m in shown[:500]],
            "note": ("Opened is reliable; not opened is not proof the email "
                     "was unread — many mail apps block pictures.")}


@router.post("/refresh")
async def refresh(session: AsyncSession = Depends(get_session),
                  user=Depends(require_role("admin", "super_admin"))):
    """Read bounce notices from the sending inbox now."""
    from app.workers.email_bounce_worker import check_now
    return await asyncio.to_thread(check_now)
