"""
CSP DocMaker — one search across the app (No. 175)

  GET /api/search?q=…   every signed-in role

The header's search (Ctrl+K). Matched the one way every search box matches
(services/search_match.py): CSP name, code, phone, email, district, state,
RM — part of a word is enough. Results come grouped:

  csps          the CSPs themselves (`can_act`: an RM acts only on their
                own and unowned CSPs — owner's choice, 2 Nov 2026)
  documents     stored PDFs of those CSPs
  chats         what CSPs wrote on WhatsApp, and messages people sent them,
                containing the words searched (RMs: their own CSPs)
  action_items  Action Required cards of those CSPs (RMs: as their bell)
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_any_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def search_everything(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(6, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    return await session.run_sync(lambda s: everything(s, q, limit, user))


def everything(session, q: str, limit: int, user: dict) -> dict:
    from app.models.csp_record import CSPRecord
    from app.models.csp_reply import CspReply
    from app.models.enums import DocumentFormat
    from app.models.rm_alert import RMAlert
    from app.models.stored_document import StoredDocument
    from app.models.whatsapp_message import WhatsAppMessage
    from app.services import action_required, csp_access, search_match
    from app.services.missing_data_service import document_label

    term = search_match.normalize(q)
    out = {"query": q, "csps": [], "documents": [], "chats": [],
           "action_items": []}
    condition = search_match.csp_condition(q)
    if condition is None:
        return out

    csps = session.execute(select(CSPRecord).where(condition)
                           .order_by(*search_match.best_first(q))
                           .limit(50)).scalars().all()
    names = {c.csp_id: c.name or c.csp_id for c in csps}
    mine = {c.csp_id for c in csps if csp_access.can_access(c, user)}
    out["csps"] = [{"csp_id": c.csp_id, "name": c.name or "",
                    "district": c.district or "", "state": c.state or "",
                    "mobile": c.mobile or "", "rm_name": c.rm_name or "",
                    "can_act": c.csp_id in mine}
                   for c in csps[:limit]]
    ids = [c.csp_id for c in csps]

    if ids:
        for d in session.execute(
                select(StoredDocument.id, StoredDocument.csp_id,
                       StoredDocument.document_type, StoredDocument.version,
                       StoredDocument.created_at)
                .where(StoredDocument.csp_id.in_(ids),
                       StoredDocument.file_format == DocumentFormat.PDF)
                .order_by(StoredDocument.created_at.desc()).limit(limit)).all():
            out["documents"].append({
                "id": str(d.id), "csp_id": d.csp_id, "name": names.get(d.csp_id, ""),
                "label": document_label(d.document_type), "version": d.version,
                "created_at": d.created_at.isoformat() if d.created_at else None})

        alerts = session.execute(action_required.visible(
            select(RMAlert).where(RMAlert.csp_id.in_(ids)), user)
            .order_by(RMAlert.created_at.desc()).limit(limit)).scalars().all()
        out["action_items"] = [action_required.row(a, names.get(a.csp_id, ""))
                               for a in alerts]

    # Chats: the words themselves, or the CSPs found above.
    like = f"%{term}%"
    replies = session.execute(
        select(CspReply).where(or_(cast(CspReply.messages, String).ilike(like),
                                   CspReply.csp_id.in_(ids or [""])))
        .order_by(CspReply.created_at.desc()).limit(50)).scalars().all()
    sent = session.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.body_text.ilike(like))
        .order_by(WhatsAppMessage.sent_at.desc()).limit(20)).scalars().all()
    seen = set()
    for csp_id, text, at in (
            [(r.csp_id, next((m.get("text", "") for m in (r.messages or [])
                              if term in search_match.normalize(m.get("text", ""))),
                             (r.messages or [{}])[-1].get("text", "")),
              r.last_in_at or r.created_at) for r in replies]
            + [(m.csp_id, m.body_text, m.sent_at) for m in sent]):
        if not csp_id or csp_id in seen:
            continue
        if not csp_access.is_admin(user) and csp_id not in mine:
            record = session.execute(select(CSPRecord).where(
                CSPRecord.csp_id == csp_id)).scalars().first()
            if record is None or not csp_access.can_access(record, user):
                continue
        seen.add(csp_id)
        out["chats"].append({"csp_id": csp_id, "name": names.get(csp_id, ""),
                             "snippet": (text or "")[:140],
                             "at": at.isoformat() if at else None})
        if len(out["chats"]) >= limit:
            break
    return out
