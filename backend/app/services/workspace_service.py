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
                           owner_name: str, starter: str = "blank") -> Workspace:
    """A new, empty workspace with its creator as its first Super Admin.

    It has no data sources, so no background job has anything to read for
    it until its Super Admin connects one.
    """
    from app.services import workspace_rules

    email = owner_email.strip().lower()
    with all_workspaces():
        ws = Workspace(id=uuid.uuid4(), slug=_slug(name),
                       name=clean_name(name), owner_email=email,
                       # Its Owner's own domain until they choose (No. 120).
                       settings=workspace_rules.starting_rules(email))
        session.add(ws)
        await session.flush()
        session.add(WorkspaceMember(
            workspace_id=ws.id, email=email, name=owner_name,
            role=UserRole.SUPER_ADMIN, active=True, added_by_email=None,
        ))
        await session.flush()
    if starter == "eko":
        await _starter_like_eko(session, ws)
    logger.info("workspace_service: %s created workspace %r (%s), starter %s",
                email, ws.name, ws.slug, starter)
    return ws


async def _starter_like_eko(session, ws) -> None:
    """No. 215 (ZU-08), No. 247: the ready-made start — the message wordings
    (signed with this workspace's name), the four documents SWITCHED OFF for
    review, a sample signature, and the dashboards.

    The four documents are the SAMPLE designs (templates/samples, made by
    scripts/make_sample_templates.py): a made-up organisation, bank, people
    and contacts, a "Your logo" box and a sample signature — nothing of
    Eko's, nor of any other workspace. None of Eko's records, people,
    connections or Knowledge Base answers are copied; connections start
    blank."""
    from app.services.document_template_service import (
        sync_builtin_dashboards, sync_builtin_messages)
    from app.workspace_context import workspace
    with workspace(ws.id):
        for row in sample_documents(ws.id):
            session.add(row)
        sample = sample_signature(ws.id)
        if sample is not None:
            session.add(sample)
        await sync_builtin_messages(session, signature=f"Team {ws.name}")
        await sync_builtin_dashboards(session)
        await session.flush()


def samples_dir() -> str:
    """templates/samples, beside the supplied designs' folder."""
    import os
    from app.config import get_settings
    return os.path.join(os.path.dirname(os.path.abspath(
        get_settings().server.document_templates_dir)), "samples")


def sample_documents(workspace_id) -> list:
    """The four sample documents as new rows of this workspace, switched off.
    A sample file that is missing is logged and skipped, never replaced by
    Eko's."""
    import hashlib
    import os
    from app.models.document_template import DocumentTemplate
    from app.models.enums import DocumentType
    from app.services import template_service as ts
    spot = None
    sig = os.path.join(samples_dir(), "sample-signature.png")
    if os.path.isfile(sig):
        with open(sig, "rb") as f:
            spot = "picture:" + hashlib.sha256(f.read()).hexdigest()
    rows = []
    for member in DocumentType:
        name = ts.TEMPLATE_FILES.get(member) or ""
        path = os.path.join(samples_dir(), name)
        if name and not os.path.isfile(path) and os.path.isdir(samples_dir()):
            # "ID Card.docx" and "ID_Card.docx" are the same file, as on the
            # real path (template_service._same_name).
            for entry in sorted(os.listdir(samples_dir())):
                if entry.lower().endswith(".docx") and ts._same_name(entry, name):
                    path = os.path.join(samples_dir(), entry)
                    break
        if not name or not os.path.isfile(path):
            logger.error("workspace_service.sample_documents: the sample %s is "
                         "missing (%s) — this document is not added", member.name, path)
            continue
        with open(path, "rb") as f:
            data = f.read()
        rows.append(DocumentTemplate(
            workspace_id=workspace_id, code=member.name,
            name=ts.BUILTIN_LABELS.get(member, member.name), filename=name,
            file_data=data, file_size=len(data),
            checksum=hashlib.sha256(data).hexdigest(),
            placeholder_map=dict(ts.PLACEHOLDER_FIELDS.get(member, {})),
            photo_marker=ts.PHOTO_MARKERS.get(member), is_builtin=True,
            active=False, version=1, signature_spot=spot))
    return rows


def sample_signature(workspace_id):
    """The made-up 'Sample signature' picture, for the Signatures screen."""
    import os
    from app.models.signature import Signature
    from app.services import signature_rules
    path = os.path.join(samples_dir(), "sample-signature.png")
    if not os.path.isfile(path):
        logger.error("workspace_service.sample_signature: %s is missing", path)
        return None
    with open(path, "rb") as f:
        png, width, height = signature_rules.check_picture(f.read())
    return Signature(workspace_id=workspace_id, name="Sample signature", image=png,
                     width=width, height=height,
                     checksum=signature_rules.sha256(png), created_by="ready-made start")


async def memberships(session, email: str) -> List[tuple]:
    """Every workspace this person may enter: [(member, workspace), ...].

    A workspace whose rules do not allow this person's email domain is left
    out (No. 120) — sign-in, choosing a workspace and every request go
    through here, so that one check covers them all."""
    from app.services import workspace_rules

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
    allowed = [(m, w) for m, w in rows
               if workspace_rules.email_allowed(w, address)]
    if len(allowed) < len(rows):
        logger.info("workspace_service.memberships: %d workspace(s) left out "
                    "for an address their rules do not allow",
                    len(rows) - len(allowed))
    return allowed


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


async def sheet_super_admins(session):
    """Active Super Admins of Eko SBI Kiosk CSP, from the SuperAdmins tab.

    Read from the mirrored copy (authorization_records), refreshed every 15
    minutes. Returns None when the tab has never been mirrored — which means
    "unknown", not "nobody": callers must then change nothing, or a Google
    outage would demote every Super Admin.
    """
    from app.models.authorization_record import AuthorizationRecord

    eko = await eko_workspace(session)
    if eko is None:
        return None
    with all_workspaces():
        rows = (await session.execute(
            select(AuthorizationRecord.email, AuthorizationRecord.active)
            .where(AuthorizationRecord.workspace_id == eko.id,
                   AuthorizationRecord.role == UserRole.SUPER_ADMIN)
        )).all()
    if not rows:
        return None
    return {email.strip().lower() for email, active in rows if active}
