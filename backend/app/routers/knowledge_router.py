"""
CSP DocMaker — Admin -> Knowledge Base (tracker No. 116)

  GET    /api/admin/knowledge                 every entry
  POST   /api/admin/knowledge                 add one
  PUT    /api/admin/knowledge/{id}            change one
  DELETE /api/admin/knowledge/{id}            remove one
  POST   /api/admin/knowledge/try             what the chat would answer
  GET    /api/admin/knowledge/misses          questions the chat could not answer
  DELETE /api/admin/knowledge/misses/{id}     dismiss one

Admins and Super Admins (chosen 19 Oct 2026). Every change is written to
the audit log with who made it. Entries belong to the workspace in force —
the query scoping in workspace_context keeps one workspace's entries out of
another's.
"""

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.knowledge import KnowledgeEntry, KnowledgeMiss
from app.services import knowledge_service
from app.workspace_context import current_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/knowledge", tags=["knowledge"])
require_editor = require_role("admin", "super_admin")


class EntryIn(BaseModel):
    question: str = Field(..., max_length=300)
    phrasings: str = Field("", max_length=4000)
    keywords: str = Field("", max_length=500)
    answer: str = Field(..., max_length=4000)
    category: str = Field("General", max_length=100)
    active: bool = True
    # The unanswered question this entry was written for, if any: it is
    # removed from the list once the entry is saved.
    from_miss: Optional[str] = None

    @field_validator("question", "answer")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        return v.strip() or "General"


class TryIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


def _who(user: dict) -> str:
    return (user.get("sub") or user.get("email") or "").lower()


def _out(e: KnowledgeEntry) -> dict:
    return {"id": str(e.id), "question": e.question, "phrasings": e.phrasings,
            "keywords": e.keywords, "answer": e.answer,
            "category": e.category, "active": e.active,
            "updated_by": e.updated_by,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None}


def _audit(session, user, action: str, entry_id, question: str) -> None:
    session.add(AuditLog(
        workspace_id=current_workspace_id(), action=action,
        resource_type="knowledge_entry", resource_id=str(entry_id),
        result="success",
        metadata_json={"by": _who(user), "question": question[:300]}))


async def _entry(session, entry_id: str) -> KnowledgeEntry:
    try:
        key = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    entry = (await session.execute(select(KnowledgeEntry).where(
        KnowledgeEntry.id == key))).scalars().first()
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found.")
    return entry


@router.get("")
async def list_entries(session: AsyncSession = Depends(get_session),
                       user=Depends(require_editor)):
    rows = (await session.execute(select(KnowledgeEntry).order_by(
        KnowledgeEntry.category, KnowledgeEntry.question))).scalars().all()
    return {"entries": [_out(e) for e in rows]}


async def _drop_miss(session, miss_id: Optional[str]) -> None:
    if not miss_id:
        return
    try:
        key = uuid.UUID(miss_id)
    except ValueError:
        return
    miss = (await session.execute(select(KnowledgeMiss).where(
        KnowledgeMiss.id == key))).scalars().first()
    if miss is not None:
        await session.delete(miss)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_entry(body: EntryIn, session: AsyncSession = Depends(get_session),
                    user=Depends(require_editor)):
    entry = KnowledgeEntry(
        question=body.question, phrasings=body.phrasings.strip(),
        keywords=body.keywords.strip(), answer=body.answer,
        category=body.category, active=body.active, updated_by=_who(user))
    session.add(entry)
    await session.flush()
    await _drop_miss(session, body.from_miss)
    _audit(session, user, "knowledge_add", entry.id, entry.question)
    await session.commit()
    await session.refresh(entry)
    logger.info("knowledge_router: %s added entry %s", _who(user), entry.id)
    return _out(entry)


@router.put("/{entry_id}")
async def change_entry(entry_id: str, body: EntryIn,
                       session: AsyncSession = Depends(get_session),
                       user=Depends(require_editor)):
    entry = await _entry(session, entry_id)
    entry.question, entry.answer = body.question, body.answer
    entry.phrasings, entry.keywords = body.phrasings.strip(), body.keywords.strip()
    entry.category, entry.active = body.category, body.active
    entry.updated_by = _who(user)
    await _drop_miss(session, body.from_miss)
    _audit(session, user, "knowledge_change", entry.id, entry.question)
    await session.commit()
    await session.refresh(entry)
    logger.info("knowledge_router: %s changed entry %s", _who(user), entry.id)
    return _out(entry)


@router.delete("/{entry_id}")
async def delete_entry(entry_id: str,
                       session: AsyncSession = Depends(get_session),
                       user=Depends(require_editor)):
    entry = await _entry(session, entry_id)
    _audit(session, user, "knowledge_delete", entry.id, entry.question)
    await session.delete(entry)
    await session.commit()
    logger.info("knowledge_router: %s deleted entry %s", _who(user), entry_id)
    return {"deleted": True}


@router.post("/try")
async def try_question(body: TryIn, session: AsyncSession = Depends(get_session),
                       user=Depends(require_editor)):
    """Which entries a question matches, with scores — to check a new entry
    is found the way people will ask."""
    matches = await knowledge_service.find(session, body.question)
    return {"answer_at": knowledge_service.ANSWER_AT,
            "suggest_at": knowledge_service.SUGGEST_AT,
            "matches": [{"id": str(m.entry.id), "question": m.entry.question,
                         "score": round(m.score, 2)} for m in matches[:5]]}


@router.get("/misses")
async def list_misses(session: AsyncSession = Depends(get_session),
                      user=Depends(require_editor)):
    rows = (await session.execute(select(KnowledgeMiss).order_by(
        KnowledgeMiss.times_asked.desc(), KnowledgeMiss.last_asked_at.desc())
        .limit(200))).scalars().all()
    return {"misses": [{
        "id": str(m.id), "question": m.question, "times_asked": m.times_asked,
        "last_asked_by": m.last_asked_by,
        "last_asked_at": m.last_asked_at.isoformat() if m.last_asked_at else None,
    } for m in rows]}


@router.delete("/misses/{miss_id}")
async def dismiss_miss(miss_id: str, session: AsyncSession = Depends(get_session),
                       user=Depends(require_editor)):
    try:
        key = uuid.UUID(miss_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found.")
    miss = (await session.execute(select(KnowledgeMiss).where(
        KnowledgeMiss.id == key))).scalars().first()
    if miss is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found.")
    await session.delete(miss)
    await session.commit()
    logger.info("knowledge_router: %s dismissed an unanswered question",
                _who(user))
    return {"dismissed": True}
