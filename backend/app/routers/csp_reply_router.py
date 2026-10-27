"""
CSP DocMaker — replies to CSPs' WhatsApp messages (tracker No. 151)

  * GET  /api/admin/csp-replies               the replies, waiting first
  * POST /api/admin/csp-replies/{id}/send     send it (edited text allowed)
  * POST /api/admin/csp-replies/{id}/skip     do not send it
  * GET  /api/admin/csp-replies/mode          off / draft / auto
  * PUT  /api/admin/csp-replies/mode          change it — Super Admin only

Admins and Super Admins (both may send messages to CSPs, No. 88). Every
send, skip and switch is audited.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/csp-replies", tags=["csp-replies"])

ADMINS = ("admin", "super_admin")


def _who(user) -> str:
    return (user or {}).get("sub") or (user or {}).get("email") or "unknown"


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=900)


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(off|draft|auto)$")


def _audit(session, user, action: str, reply_id: str, extra: dict) -> None:
    from app.models.audit_log import AuditLog
    session.add(AuditLog(action=action, resource_type="csp_reply",
                         resource_id=reply_id, csp_id=extra.pop("csp_id", None),
                         result="success",
                         metadata_json={"by": _who(user), **extra}))


@router.get("/mode")
async def get_mode(session: AsyncSession = Depends(get_session),
                   user=Depends(require_role(*ADMINS))):
    from app.services import csp_replies
    return {"mode": await session.run_sync(csp_replies.get_mode)}


@router.put("/mode")
async def set_mode(body: ModeIn, session: AsyncSession = Depends(get_session),
                   user=Depends(require_role("super_admin"))):
    from app.services import csp_replies
    before = await session.run_sync(csp_replies.get_mode)
    mode = await session.run_sync(csp_replies.set_mode, body.mode)
    _audit(session, user, "csp_replies_mode", "mode",
           {"from": before, "to": mode})
    await session.commit()
    logger.info("csp_reply_router: %s switched CSP replies %s -> %s",
                _who(user), before, mode)
    return {"mode": mode}


class WordingIn(BaseModel):
    intent: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=900)


@router.get("/learning")
async def learning(days: int = Query(30, ge=1, le=365),
                   session: AsyncSession = Depends(get_session),
                   user=Depends(require_role(*ADMINS))):
    """No. 154: drafts sent as they were, changed or skipped, per kind."""
    from app.services import csp_replies
    return await session.run_sync(csp_replies.learning, days)


@router.post("/learning/use")
async def use_wording(body: WordingIn, session: AsyncSession = Depends(get_session),
                      user=Depends(require_role(*ADMINS))):
    """A person's edit becomes the agent's wording (a Knowledge Base entry)."""
    from app.services import csp_replies
    try:
        question = await session.run_sync(csp_replies.use_wording, body.intent,
                                          body.text, _who(user))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    _audit(session, user, "csp_reply_wording", body.intent,
           {"entry": question, "text": body.text})
    await session.commit()
    return {"entry": question, "text": body.text}


@router.get("")
async def list_replies(
    status_: str = Query("", alias="status",
                         pattern="^(|draft|sent|skipped|failed|expired)$"),
    limit: int = Query(100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    from app.models.csp_record import CSPRecord
    from app.models.csp_reply import CspReply
    from app.services import csp_replies

    query = (select(CspReply, CSPRecord.name)
             .outerjoin(CSPRecord, CSPRecord.csp_id == CspReply.csp_id))
    if status_:
        query = query.where(CspReply.status == status_)
    rows = (await session.execute(
        query.order_by((CspReply.status != "draft"),
                       CspReply.last_in_at.desc()).limit(limit))).all()
    waiting = sum(1 for r, _ in rows if r.status == "draft")
    return {"mode": await session.run_sync(csp_replies.get_mode),
            "waiting": waiting,
            "replies": [csp_replies.as_row(r, name or "") for r, name in rows]}


async def _reply(session: AsyncSession, reply_id: str):
    from app.models.csp_reply import CspReply
    try:
        key = uuid.UUID(reply_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such reply.")
    reply = await session.get(CspReply, key)
    if reply is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such reply.")
    return reply


@router.post("/{reply_id}/send")
async def send_reply(reply_id: str, body: SendIn,
                     session: AsyncSession = Depends(get_session),
                     user=Depends(require_role(*ADMINS))):
    from app.services import csp_replies

    reply = await _reply(session, reply_id)
    if reply.status not in ("draft", "failed"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This reply is already {reply.status}.")
    try:
        await session.run_sync(csp_replies.send, reply, _who(user), body.text)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    _audit(session, user, "csp_reply_send", reply_id,
           {"csp_id": reply.csp_id, "status": reply.status,
            "action": reply.action, "note": reply.note})
    await session.commit()
    return csp_replies.as_row(reply)


@router.post("/{reply_id}/skip")
async def skip_reply(reply_id: str, session: AsyncSession = Depends(get_session),
                     user=Depends(require_role(*ADMINS))):
    from app.services import csp_replies

    reply = await _reply(session, reply_id)
    if reply.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This reply is already {reply.status}.")
    reply.status, reply.decided_by, reply.note = "skipped", _who(user), "skipped"
    _audit(session, user, "csp_reply_skip", reply_id, {"csp_id": reply.csp_id})
    await session.commit()
    return csp_replies.as_row(reply)
