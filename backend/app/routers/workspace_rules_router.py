"""
CSP DocMaker — Setup → Workspace Rules (tracker No. 120)

  GET /api/admin/workspace-rules   this workspace's rules (Admins and Owner —
                                   Admins need them to know whether they may
                                   manage members)
  PUT /api/admin/workspace-rules   change them (Workspace Owner only)

What the rules are and where each is enforced: services/workspace_rules.py.
Every change is written to the audit log with what it was before.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.enums import UserRole
from app.models.messaging import MessageTemplate
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.services import workspace_rules
from app.workspace_context import require_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/workspace-rules",
                   tags=["admin", "workspace-rules"])


class RulesIn(BaseModel):
    allowed_email_domains: list[str] = Field(default_factory=list,
                                             max_length=50)
    session_hours: int
    members_added_by: str = workspace_rules.OWNER_ONLY
    message_signoff: str = ""


def _who(user: dict) -> str:
    return (user.get("sub") or user.get("email") or "").lower()


async def _workspace(session) -> Workspace:
    ws = (await session.execute(select(Workspace).where(
        Workspace.id == require_workspace_id()))).scalars().first()
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return ws


def _out(ws: Workspace) -> dict:
    return {"workspace": {"id": str(ws.id), "name": ws.name},
            **workspace_rules.describe(ws)}


@router.get("")
async def get_rules(session: AsyncSession = Depends(get_session),
                    user=Depends(require_role("admin", "super_admin"))):
    return _out(await _workspace(session))


@router.put("")
async def set_rules(body: RulesIn,
                    session: AsyncSession = Depends(get_session),
                    user=Depends(require_role("super_admin"))):
    ws = await _workspace(session)
    owners = (await session.execute(select(WorkspaceMember.email).where(
        WorkspaceMember.role == UserRole.SUPER_ADMIN,
        WorkspaceMember.active.is_(True)))).scalars().all()
    try:
        new = workspace_rules.validated(body.model_dump(), list(owners))
    except workspace_rules.RuleError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    before = workspace_rules.describe(ws)
    ws.settings = {**(ws.settings or {}), **new}

    # A new sign-off goes onto every message wording that ends with one.
    resigned, whatsapp = [], False
    if new["message_signoff"] and (new["message_signoff"]
                                   != before["message_signoff"]):
        for t in (await session.execute(select(MessageTemplate))).scalars():
            changed = workspace_rules.resign(t.body, new["message_signoff"])
            if changed is not None:
                t.body = changed
                resigned.append(t.name)
                whatsapp = whatsapp or t.channel_kind == "whatsapp"

    session.add(AuditLog(
        workspace_id=ws.id, action="workspace_rules_change",
        resource_type="workspace", resource_id=str(ws.id), result="success",
        metadata_json={"by": _who(user),
                       "before": {k: before[k] for k in new},
                       "after": new, "wordings_resigned": resigned}))
    await session.commit()
    await session.refresh(ws)
    logger.info("workspace_rules_router: %s changed the rules of %s "
                "(%d wording(s) re-signed)", _who(user), ws.slug,
                len(resigned))
    out = _out(ws)
    out["wordings_resigned"] = resigned
    if whatsapp:
        out["note"] = ("WhatsApp wordings with the new sign-off need Meta's "
                       "approval once before they are delivered (minutes to "
                       "about a day).")
    return out
