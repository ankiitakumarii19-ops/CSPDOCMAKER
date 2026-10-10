"""
CSP DocMaker — creating workspaces and answering "who belongs where"

Every lookup here reads across workspaces on purpose (`all_workspaces()`):
at sign-in nobody has a workspace yet, and deciding which one they may enter
is exactly the question being asked. Nothing here returns a workspace's
DATA — only whether a person belongs to it, and as what.
"""

import logging
import re
import secrets
import uuid
from typing import List, Optional

from sqlalchemy import select

from app.models.enums import UserRole
from app.models.workspace import DEFAULT_SLUG, Workspace
from app.models.workspace_member import WorkspaceMember
from app.workspace_context import all_workspaces

logger = logging.getLogger(__name__)

NAME_MIN, NAME_MAX = 3, 100


def clean_name(name: str) -> str:
    """A workspace name with surrounding and repeated spaces removed."""
    return re.sub(r"\s+", " ", (name or "").strip())


def name_problem(name: str) -> Optional[str]:
    """Why this name cannot be used, or None if it can."""
    name = clean_name(name)
    if len(name) < NAME_MIN:
        return f"A workspace name needs at least {NAME_MIN} characters."
    if len(name) > NAME_MAX:
        return f"A workspace name can be at most {NAME_MAX} characters."
    return None


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", clean_name(name).lower()).strip("-")
    # A random tail, so two workspaces with the same name never collide and
    # a slug cannot be guessed from a name.
    return f"{(base or 'workspace')[:60]}-{secrets.token_hex(3)}"


async def name_taken(session, name: str) -> bool:
    with all_workspaces():
        found = (await session.execute(
            select(Workspace.id).where(
                Workspace.name.ilike(clean_name(name)))
        )).first()
    return found is not None


async def create_workspace(session, name: str, owner_email: str,
                           owner_name: str) -> Workspace:
    """A new, empty workspace with its creator as its first Super Admin.

    It has no data sources, so no background job has anything to read for
    it until its Super Admin connects one.
    """
    email = owner_email.strip().lower()
    with all_workspaces():
        ws = Workspace(id=uuid.uuid4(), slug=_slug(name),
                       name=clean_name(name), owner_email=email)
        session.add(ws)
        await session.flush()
        session.add(WorkspaceMember(
            workspace_id=ws.id, email=email, name=owner_name,
            role=UserRole.SUPER_ADMIN, active=True, added_by_email=None,
        ))
        await session.flush()
    logger.info("workspace_service: %s created workspace %r (%s)",
                email, ws.name, ws.slug)
    return ws


async def memberships(session, email: str) -> List[tuple]:
    """Every workspace this person may enter: [(member, workspace), ...]."""
    address = (email or "").strip().lower()
    with all_workspaces():
        rows = (await session.execute(
            select(WorkspaceMember, Workspace)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(WorkspaceMember.email == address,
                   WorkspaceMember.active.is_(True),
                   Workspace.active.is_(True))
            .order_by(Workspace.created_at)
        )).all()
    return [(m, w) for m, w in rows]


async def membership(session, email: str,
                     workspace_id) -> Optional[WorkspaceMember]:
    """This person's active membership of this workspace, or None."""
    if isinstance(workspace_id, str):
        try:
            workspace_id = uuid.UUID(workspace_id)
        except ValueError:
            return None
    for member, ws in await memberships(session, email):
        if ws.id == workspace_id:
            return member
    return None


async def eko_workspace(session) -> Optional[Workspace]:
    """The workspace that owns the sheets configured in the environment."""
    with all_workspaces():
        return (await session.execute(
            select(Workspace).where(Workspace.slug == DEFAULT_SLUG)
        )).scalars().first()


async def is_eko(session, workspace_id) -> bool:
    ws = await eko_workspace(session)
    return ws is not None and str(ws.id) == str(workspace_id)


async def has_any_membership(session, email: str) -> bool:
    """Whether this person has ever had a membership, active or not."""
    with all_workspaces():
        return (await session.execute(
            select(WorkspaceMember.id).where(
                WorkspaceMember.email == (email or "").strip().lower())
        )).first() is not None
