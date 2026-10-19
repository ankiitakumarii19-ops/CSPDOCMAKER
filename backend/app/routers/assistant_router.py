"""
CSP DocMaker — the ask-anything chat (tracker No. 114)

  POST   /api/assistant/chat                  a question in, an answer + cards out
  POST   /api/assistant/drafts/{id}/send      the person pressed Send
  DELETE /api/assistant/drafts/{id}           the person pressed Cancel
  GET    /api/assistant/documents/{id}        a PDF the chat offered for download

RM, Admin and Super Admin. RMs get answers about their own CSPs only — every
lookup goes through assistant_tools, which applies csp_access; downloads and
sends check it again here, so a draft or a document id cannot be used to
reach another RM's CSP.

No AI model (tracker No. 116, 19 Oct 2026): assistant_engine answers by
fixed rules from the records and the Knowledge Base. A draft goes out only
on the Send press, exactly as previewed, once (the draft is removed as it is
taken), and every send is written to the audit log.
"""

import asyncio
import logging
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.csp_record import CSPRecord
from app.models.stored_document import StoredDocument
from app.services import (assistant_engine, assistant_tools, csp_access,
                          document_storage_service)
from app.workspace_context import current_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
require_user = require_role("rm", "admin", "super_admin")

MAX_HISTORY = 12


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class ChatIn(BaseModel):
    messages: List[ChatTurn] = Field(..., min_length=1)


def _who(user: dict) -> str:
    return (user.get("sub") or user.get("email") or "").lower()


@router.post("/chat")
async def chat(body: ChatIn, session: AsyncSession = Depends(get_session),
               user=Depends(require_user)):
    """One question answered by fixed rules from the records and the
    Knowledge Base. The screen sends the conversation so far (text only) so
    "his RBO number" can follow a question about a CSP."""
    history = [t.model_dump() for t in body.messages[-MAX_HISTORY:]]
    if history[-1]["role"] != "user":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "The last message must be the question.")
    question = history[-1]["content"].strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "The question is empty.")
    result = await assistant_engine.answer(question, history[:-1], session,
                                           user)
    logger.info("assistant_router.chat: %s, %d turn(s), answer %s, %d "
                "card(s)", _who(user), len(history), result.kind,
                len(result.cards))
    return {"reply": result.reply, "cards": result.cards,
            "suggestions": result.suggestions}


# ---- drafts ----------------------------------------------------------------

async def _own_draft(draft_id: str, user: dict) -> dict:
    draft = await assistant_tools.take_draft(draft_id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "This draft has expired or was already sent or "
                            "cancelled. Ask the chat for a new one.")
    if draft.get("owner") != _who(user) or draft.get("workspace_id") != str(
            current_workspace_id() or ""):
        # Someone else's draft: put it back untouched and refuse.
        await assistant_tools.put_back(draft)
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "This draft has expired or was already sent or "
                            "cancelled. Ask the chat for a new one.")
    return draft


async def _audit(session: AsyncSession, user: dict, draft: dict,
                 result: str, detail: dict) -> None:
    """Record the send. Never undoes a message that went out."""
    try:
        async with session.begin_nested():
            session.add(AuditLog(
                workspace_id=current_workspace_id(),
                action="assistant_message",
                resource_type="csp", resource_id=draft["csp_id"],
                csp_id=draft["csp_id"], result=result,
                metadata_json={"by": _who(user), "channel": draft["channel"],
                               "draft_id": draft["id"], **detail}))
        await session.commit()
    except Exception as e:
        logger.error("assistant_router: could not audit the %s send of draft "
                     "%s for CSP %s: %s: %s", draft["channel"], draft["id"],
                     draft["csp_id"], type(e).__name__, e, exc_info=True)


@router.post("/drafts/{draft_id}/send")
async def send_draft(draft_id: str,
                     session: AsyncSession = Depends(get_session),
                     user=Depends(require_user)):
    """Send a draft exactly as previewed. Reports honestly what happened."""
    draft = await _own_draft(draft_id, user)
    csp = (await session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == draft["csp_id"]))).scalars().first()
    if csp is None or not csp_access.can_access(csp, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "This CSP is no longer among the CSPs you may "
                            "message. Nothing was sent.")

    if draft["channel"] == assistant_tools.WHATSAPP:
        outcome = await _send_whatsapp(session, draft, csp)
    else:
        outcome = await _send_email(draft)

    state = outcome["state"]
    await _audit(session, user, draft, "success" if state == "sent" else
                 ("pending" if state == "pending" else "failure"),
                 {"state": state, "reason": outcome.get("reason", "")[:300]})
    if state == "failed":
        # Definitely not sent: keep the draft so Send can be pressed again.
        try:
            await assistant_tools.put_back(draft)
        except Exception as e:
            logger.error("assistant_router.send_draft: could not keep draft "
                         "%s for a retry: %s: %s", draft["id"],
                         type(e).__name__, e, exc_info=True)
    logger.info("assistant_router.send_draft: %s, CSP %s by %s: %s %s",
                _who(user), draft["csp_id"], draft["channel"], state,
                outcome.get("reason", ""))
    return {"draft_id": draft["id"], "channel": draft["channel"],
            "to": draft["to"], **outcome}


async def _send_whatsapp(session: AsyncSession, draft: dict, csp) -> dict:
    from app.models.whatsapp_message import KIND_OTHER
    from app.services import message_log, whatsapp_platform as wa

    result = await asyncio.to_thread(
        wa.send, draft["to"], assistant_tools.WHATSAPP_WORDING,
        {"name": csp.name or "CSP", "message": draft["message"]},
        source_name=message_log.source_name("chat", csp.csp_id))
    await session.run_sync(lambda s: message_log.record(
        s, kind=KIND_OTHER, mobile=draft["to"], outcome=result,
        csp_id=csp.csp_id, csp_name=csp.name))
    await session.commit()

    if result["status"] == wa.SENT:
        return {"state": "sent", "reason": ""}
    if result["status"] == wa.PENDING:
        return {"state": "pending", "reason": (
            "WhatsApp is checking this message's wording (only needed the "
            "first time; minutes to about a day). It has NOT been delivered "
            "yet — try Send again later, or send it by email.")}
    if result["status"] == wa.REJECTED:
        return {"state": "rejected", "reason": result.get("reason", "")}
    return {"state": "failed", "reason": result.get("reason", "")}


async def _send_email(draft: dict) -> dict:
    from app.services import message_sender

    ok, why = await asyncio.to_thread(
        message_sender._send_email, draft["to"], draft["subject"],
        draft["preview"])
    return {"state": "sent" if ok else "failed", "reason": why}


@router.delete("/drafts/{draft_id}")
async def cancel_draft(draft_id: str, user=Depends(require_user)):
    draft = await _own_draft(draft_id, user)
    logger.info("assistant_router.cancel_draft: %s cancelled the %s draft for "
                "CSP %s", _who(user), draft["channel"], draft["csp_id"])
    return {"cancelled": True}


# ---- documents ---------------------------------------------------------------

@router.get("/documents/{document_id}")
async def download_document(document_id: str,
                            session: AsyncSession = Depends(get_session),
                            user=Depends(require_user)):
    """One stored PDF, if the person may see its CSP. Checksum verified."""
    import uuid as _uuid
    not_found = HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    try:
        key = _uuid.UUID(document_id)
    except ValueError:
        raise not_found
    doc = (await session.execute(select(StoredDocument).where(
        StoredDocument.id == key))).scalars().first()
    if doc is None:
        raise not_found
    csp = (await session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == doc.csp_id))).scalars().first()
    if csp is None or not csp_access.can_access(csp, user):
        raise not_found
    if not document_storage_service.verify_integrity(doc):
        logger.error("assistant_router: stored document %s failed its "
                     "checksum", document_id)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This stored file failed its integrity check.")
    return Response(doc.file_data, media_type=doc.content_type, headers={
        "Content-Disposition": f'attachment; filename="{doc.filename}"',
        "Cache-Control": "private, no-store"})


# ---- setting up the workspace (No. 117) -------------------------------------------

require_owner = require_role("super_admin")


@router.get("/setup")
async def setup_status(session: AsyncSession = Depends(get_session),
                       user=Depends(require_user)):
    """The Owner's setup checklist, for the chat to open with while the
    workspace is not ready. Quick: sheets are not opened here (asking
    "setup status" in the chat does open them)."""
    from app.services import workspace_setup
    if not workspace_setup.is_owner(user):
        return {"owner": False, "complete": True}
    steps = await workspace_setup.checklist(session, user, live=False)
    summary = workspace_setup.summary(steps)
    return {"owner": True, **summary,
            "reply": workspace_setup.reply_for(steps),
            "cards": [{"type": "setup", **summary,
                       "steps": [s.card() for s in steps]}]}


async def _own_action(action_id: str, user: dict) -> dict:
    gone = HTTPException(status.HTTP_404_NOT_FOUND,
                         "This has expired or was already done or cancelled. "
                         "Ask the chat again.")
    action = await assistant_tools.take_action(action_id)
    if action is None:
        raise gone
    if action.get("owner") != _who(user) or action.get("workspace_id") != str(
            current_workspace_id() or ""):
        await assistant_tools.put_back_action(action)
        raise gone
    return action


@router.post("/actions/{action_id}/run")
async def run_action(action_id: str,
                     session: AsyncSession = Depends(get_session),
                     user=Depends(require_owner)):
    """The Owner pressed Do it: run the proposed setup action once, through
    the same server functions the setup screens use, and audit it."""
    from app.services import workspace_setup
    action = await _own_action(action_id, user)
    outcome = await workspace_setup.run(action["kind"], action["params"],
                                        session, user)
    try:
        session.add(AuditLog(
            workspace_id=current_workspace_id(),
            action="assistant_setup_action", resource_type="workspace",
            resource_id=str(current_workspace_id() or ""),
            result="success" if outcome["ok"] else "failure",
            metadata_json={"by": _who(user), "kind": action["kind"],
                           "params": action["params"],
                           "message": outcome["message"][:300]}))
        await session.commit()
    except Exception as e:
        logger.error("assistant_router.run_action: could not audit the %s "
                     "action: %s: %s", action["kind"], type(e).__name__, e,
                     exc_info=True)
    logger.info("assistant_router.run_action: %s ran %s: %s", _who(user),
                action["kind"], "done" if outcome["ok"] else "refused")
    nxt = None
    if outcome["ok"]:
        steps = await workspace_setup.checklist(session, user, live=False)
        todo = [s for s in steps if s.status == workspace_setup.TODO]
        if todo:
            nxt = {"title": todo[0].title, "ask": todo[0].ask
                   or "Setup status"}
    return {"ok": outcome["ok"], "message": outcome["message"], "next": nxt}


@router.delete("/actions/{action_id}")
async def cancel_action(action_id: str, user=Depends(require_owner)):
    action = await _own_action(action_id, user)
    logger.info("assistant_router.cancel_action: %s cancelled %s", _who(user),
                action["kind"])
    return {"cancelled": True}


@router.get("/status")
async def assistant_status(user=Depends(require_user)):
    """Whether the chat can answer. It needs no outside service, so always."""
    return {"available": True, "provider": "rules"}
