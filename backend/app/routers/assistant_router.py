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

Nothing is sent by the AI model. A draft goes out only on the Send press,
exactly as previewed, once (the draft is removed as it is taken), and every
send is written to the audit log.
"""

import asyncio
import json
import logging
from datetime import date
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
from app.services import (assistant_llm, assistant_tools, csp_access,
                          document_storage_service)
from app.workspace_context import current_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
require_user = require_role("rm", "admin", "super_admin")

MAX_TOOL_ROUNDS = 5
MAX_HISTORY = 12


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class ChatIn(BaseModel):
    messages: List[ChatTurn] = Field(..., min_length=1)


def _who(user: dict) -> str:
    return (user.get("sub") or user.get("email") or "").lower()


def _system_prompt(user: dict) -> str:
    scope = ("every CSP" if csp_access.is_admin(user)
             else "only the CSPs assigned to them (they are an RM)")
    return (
        "You are the assistant inside CSP DocMaker, Eko Bharat Ventures' "
        "tool for CSPs (Customer Service Points). You help staff find CSP "
        "information, documents and contacts, and draft messages to CSPs.\n"
        f"Today is {date.today():%d %B %Y}. The person asking is "
        f"{user.get('name') or _who(user)}; they may see {scope}.\n"
        "Rules:\n"
        "- Answer ONLY from what the tools return. Never guess or invent a "
        "number, name, email or document. If a tool says something is not "
        "found or not on record, say so plainly, in the tool's words (e.g. "
        "'not found among your CSPs').\n"
        "- A CSP code is the CSP's ID. If the person gives a name or partial "
        "code, use find_csps; if several match, list them and ask which.\n"
        "- For documents, call csp_documents: the screen then shows Download "
        "buttons under your answer, so just say which documents exist.\n"
        "- To message, remind or text a CSP, call draft_message. It does NOT "
        "send. Tell the person to check the draft below and press Send. "
        "Never say a message was sent.\n"
        "- Contacts, documents and drafts appear as cards under your answer; "
        "keep your text short and do not repeat every field. Never use "
        "tables; use short sentences or a bullet list.\n"
        "- Reply in the language the person used (English, Hindi or "
        "Hinglish). Be brief and friendly.\n"
        "- You cannot change CSP data, generate documents or send email "
        "attachments; say so if asked.")


@router.post("/chat")
async def chat(body: ChatIn, session: AsyncSession = Depends(get_session),
               user=Depends(require_user)):
    """One question answered. The screen sends the conversation so far
    (text only); the model looks things up again when it needs to."""
    history = [t.model_dump() for t in body.messages[-MAX_HISTORY:]]
    if history[-1]["role"] != "user":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "The last message must be the question.")
    messages = [{"role": "system", "content": _system_prompt(user)}] + history
    cards, tools_used = [], []

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            answer = await asyncio.to_thread(
                assistant_llm.complete, messages, assistant_tools.TOOLS)
            calls = answer.get("tool_calls") or []
            if not calls:
                reply = (answer.get("content") or "").strip()
                break
            messages.append({"role": "assistant",
                             "content": answer.get("content") or "",
                             "tool_calls": calls})
            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name", "")
                data, card = await assistant_tools.run(
                    name, fn.get("arguments"), session, user)
                tools_used.append(name)
                if card is not None:
                    cards.append(card)
                messages.append({
                    "role": "tool", "tool_call_id": call.get("id", ""),
                    "name": name,
                    "content": json.dumps(data, default=str)})
        else:
            reply = ("I looked several things up but could not finish the "
                     "answer. Please ask again more simply.")
    except assistant_llm.AssistantUnavailable as e:
        logger.error("assistant_router.chat: %s asked; the AI model failed "
                     "after tools %s: %s", _who(user), tools_used, e,
                     exc_info=e.__cause__ is not None)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))

    cards = await _distinct(cards)
    if not reply:
        reply = ("Here is what I found." if cards else
                 "Sorry, I have no answer for that. Try asking with a CSP code.")
    logger.info("assistant_router.chat: %s, %d turn(s), tools %s, %d card(s)",
                _who(user), len(history), tools_used or "none", len(cards))
    return {"reply": reply, "cards": cards}


async def _distinct(cards: list) -> list:
    """One card per thing. A model that looks the same CSP up twice, or
    drafts twice, must not show two cards — or leave two drafts that could
    both be sent. The latest of each wins; earlier drafts are discarded."""
    latest = {}
    for card in cards:
        key = (card["type"], card.get("csp_id") or card.get("query"))
        earlier = latest.pop(key, None)
        if earlier is not None and earlier["type"] == "draft":
            await assistant_tools.take_draft(earlier["id"])
        latest[key] = card
    return list(latest.values())


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


@router.get("/status")
async def assistant_status(user=Depends(require_user)):
    """Whether the chat can answer, so the screen can say so up front."""
    return {"available": assistant_llm.is_configured(),
            "provider": assistant_llm.provider()}
