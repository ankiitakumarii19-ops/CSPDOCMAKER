"""
CSP DocMaker — who may sign in

Super Admin only. This is the one screen that decides who can reach the
system at all, so an Admin cannot open it — otherwise an Admin could grant
themselves anything.

Access is held in the Authorization Google Sheet and mirrored into
`authorization_records` every 15 minutes. That sheet stays the source of
truth: granting someone access here WRITES TO THE SHEET rather than only to
the database. Two reasons that matters —

  * the sync would otherwise undo it on the next pass, restoring whatever
    the sheet still said;
  * and "who can log in" would then have two answers, which is exactly the
    kind of disagreement that ends with someone keeping access after they
    were supposed to lose it.

Super Admins are not managed here. They come from configuration
(SUPER_ADMIN_EMAILS), because a Super Admin is the person who connects a
workspace's sheets in the first place.
"""

import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.dependencies import require_role
from app.models.authorization_record import AuthorizationRecord
from app.models.user import User
from app.services import google_sheets_service as gs
from app.services.sheet_writeback_service import SheetWriteError, column_letter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/access", tags=["admin", "access"])


def _who(user: dict) -> str:
    """Who is doing this, for the log and the audit trail.

    A token always carries `sub`; it does not always carry `email`, and
    logging "None" for who deleted something is worse than useless.
    """
    return (user or {}).get("email") or (user or {}).get("sub") or "unknown"


ACTIVE = "Active"
INACTIVE = "Inactive"

# Which tab holds which role.
TAB_FOR = {"rm": "rm", "admin": "admin"}


class GrantRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1)
    mobile: str = ""
    role: str = Field(..., pattern="^(rm|admin|super_admin)$")


class RevokeRequest(BaseModel):
    email: EmailStr
    role: str = Field("rm", pattern="^(rm|admin|super_admin)$")


def _tab(role: str) -> str:
    settings = get_settings()
    if role == "admin":
        return settings.google_sheets_admin_sheet_name
    if role == "rm":
        return settings.google_sheets_rm_sheet_name
    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                        f"There is no '{role}' tab.")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _columns(header: List[str]) -> dict:
    """Locate the columns by header name, as the sheet has them today."""
    found = {}
    for index, title in enumerate(header):
        key = _norm(title).replace("_", " ")
        if "email" in key:
            found.setdefault("email", index)
        elif key in ("name", "full name"):
            found.setdefault("name", index)
        elif "contact" in key or "mobile" in key or "phone" in key:
            found.setdefault("mobile", index)
        elif "status" in key:
            found.setdefault("status", index)
    return found


def _read(tab: str):
    service = gs._get_sheets_service()
    settings = get_settings()
    try:
        rows = service.spreadsheets().values().get(
            spreadsheetId=settings.google_sheets_id, range=tab,
        ).execute().get("values", [])
    except Exception as e:
        gs.reset_sheets_service()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not read the {tab} tab: {type(e).__name__}: {e}")
    if not rows:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"The {tab} tab is empty.")
    return service, rows, _columns(rows[0])


def _write_cell(tab: str, row_number: int, column: int, value: str) -> None:
    service = gs._get_sheets_service()
    settings = get_settings()
    cell = f"{tab}!{column_letter(column)}{row_number}"
    try:
        service.spreadsheets().values().update(
            spreadsheetId=settings.google_sheets_id, range=cell,
            valueInputOption="RAW", body={"values": [[value]]},
        ).execute()
    except Exception as e:
        gs.reset_sheets_service()
        if "PERMISSION_DENIED" in str(e) or "403" in str(e):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This system can read the Authorization sheet but not write "
                "to it. Share that sheet with the service account as an "
                "Editor, then try again.",
            )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not write to {tab}: {type(e).__name__}: {e}")


# ---- endpoints -----------------------------------------------------------

async def _sheet_people(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Everyone who may sign in, and whether they ever have."""
    settings = get_settings()

    records = (await session.execute(
        select(AuthorizationRecord).order_by(
            AuthorizationRecord.role, AuthorizationRecord.name)
    )).scalars().all()
    registered = {
        u.email.lower(): u for u in
        (await session.execute(select(User))).scalars().all()
    }

    people = []
    for record in records:
        account = registered.get((record.email or "").lower())
        people.append({
            "email": record.email,
            "name": record.name,
            "mobile": record.mobile,
            "role": record.role.value if hasattr(record.role, "value")
                    else str(record.role),
            "active": record.active,
            "registered": account is not None,
            "last_login": account.last_login_at.isoformat()
                          if account and account.last_login_at else None,
            "synchronized_at": record.synchronized_at.isoformat()
                               if record.synchronized_at else None,
        })

    return {
        "people": people,
        "total": len(people),
        # Shown so it is obvious these are not managed here.
        "super_admins": [],
        "source": "Authorization Google Sheet",
        "sync_interval_minutes": settings.google_sheets_sync_interval_minutes,
    }


@router.get("/logins")
async def login_history_for(
    email: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Every recorded sign-in for one person, newest first.

    The Owner's alone: knowing when a named colleague signs in is about
    the person, not about the work, and sits with the rest of access
    control rather than with the screens an Admin uses.

    `started` says when this record began. Sign-ins before that were never
    written down — only a single overwritten timestamp survived them — and
    an empty list means "nothing recorded yet", not "never signed in".
    """
    from app.services import login_history

    entries = await login_history.for_email(session, email)
    return {
        "email": email,
        "logins": entries,
        "note": (
            "Sign-ins have only been recorded since this feature was added. "
            "An empty list here does not mean the account was never used."
        ),
    }


async def _grant_in_sheet(
    request: GrantRequest,
    user=Depends(require_role("super_admin")),
):
    """Give someone RM or Admin access, by writing them into the sheet."""
    settings = get_settings()
    if not settings.email_domain_allowed(request.email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Only {settings.allowed_email_domains_text} addresses can be "
            f"given access.",
        )

    tab = _tab(request.role)
    service, rows, columns = _read(tab)
    if "email" not in columns:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The {tab} tab has no email column, so nobody can be added.")

    wanted = _norm(request.email)
    for number, row in enumerate(rows[1:], start=2):
        index = columns["email"]
        if index < len(row) and _norm(row[index]) == wanted:
            # Already listed — reactivate rather than add a second row.
            if "status" in columns:
                _write_cell(tab, number, columns["status"], ACTIVE)
                logger.info("access_router.grant_access: %s reactivated in %s "
                            "by %s", request.email, tab, _who(user))
                return {"email": request.email, "role": request.role,
                        "active": True, "action": "reactivated"}
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{request.email} is already in the {tab} tab, and that tab "
                f"has no Status column to reactivate them with.")

    # Append a new row, placing each value under its own header.
    width = max(len(rows[0]), max(columns.values()) + 1)
    new_row = [""] * width
    new_row[columns["email"]] = str(request.email)
    if "name" in columns:
        new_row[columns["name"]] = request.name.strip()
    if "mobile" in columns:
        new_row[columns["mobile"]] = request.mobile.strip()
    if "status" in columns:
        new_row[columns["status"]] = ACTIVE

    try:
        service.spreadsheets().values().append(
            spreadsheetId=settings.google_sheets_id,
            range=tab, valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [new_row]},
        ).execute()
    except Exception as e:
        gs.reset_sheets_service()
        if "PERMISSION_DENIED" in str(e) or "403" in str(e):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This system can read the Authorization sheet but not write "
                "to it. Share that sheet with the service account as an "
                "Editor, then try again.",
            )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"Could not add them to {tab}: {e}")

    logger.info("access_router.grant_access: %s added to %s by %s",
                request.email, tab, _who(user))
    return {"email": request.email, "role": request.role, "active": True,
            "action": "added",
            "note": f"They can sign in within "
                    f"{settings.google_sheets_sync_interval_minutes} minutes, "
                    f"or immediately after a sync."}


async def _revoke_in_sheet(
    request: RevokeRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Take someone's access away by marking them inactive in the sheet."""
    settings = get_settings()
    tab = _tab(request.role)
    _service, rows, columns = _read(tab)
    if "email" not in columns or "status" not in columns:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The {tab} tab needs both an email and a Status column before "
            f"access can be revoked from here.")

    wanted = _norm(request.email)
    index = columns["email"]
    for number, row in enumerate(rows[1:], start=2):
        if index < len(row) and _norm(row[index]) == wanted:
            _write_cell(tab, number, columns["status"], INACTIVE)

            # Reflect it immediately rather than waiting for the next sync,
            # so a revoked person cannot sign in during the gap.
            record = (await session.execute(
                select(AuthorizationRecord).where(
                    AuthorizationRecord.email == request.email)
            )).scalars().first()
            if record is not None:
                record.active = False
                await session.commit()

            logger.info("access_router.revoke_access: %s revoked in %s by %s",
                        request.email, tab, _who(user))
            return {"email": request.email, "role": request.role,
                    "active": False, "action": "revoked"}

    raise HTTPException(status.HTTP_404_NOT_FOUND,
                        f"{request.email} is not in the {tab} tab.")


@router.post("/sync")
async def sync_now(user=Depends(require_role("super_admin"))):
    """Pull the Authorization sheet now instead of waiting for the timer."""
    from app.workers.auth_sync_worker import sync_authorization

    try:
        result = sync_authorization.apply_async()
        return {"queued": True, "task_id": str(result.id)}
    except Exception as e:
        logger.error("access_router.sync_now: could not queue a sync: %s", e)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not start a sync: {type(e).__name__}. Is the worker "
            f"running?")


# ---- workspace membership: the source of truth for who may sign in --------
#
# Adding and removing people now happens here, per workspace. For Eko SBI
# Kiosk CSP the Authorization sheet is ALSO updated, as before — but a sheet
# that cannot be written no longer stops the person being added; the answer
# says so instead.

from app.models.enums import UserRole  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.models.workspace_member import WorkspaceMember  # noqa: E402
from app.services import workspace_service  # noqa: E402
from app.workspace_context import require_workspace_id  # noqa: E402

CARRIED_OVER = "Created the workspace, or carried over"


def _role(value: str) -> UserRole:
    return {"rm": UserRole.RM, "admin": UserRole.ADMIN,
            "super_admin": UserRole.SUPER_ADMIN}[value]


@router.get("")
async def list_access(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Everyone in this workspace, grouped by the Super Admin who added them.

    The first five keys are the shape the Access Control screen was built
    against (AccessListing in frontend/app/lib/api.ts) and must not change
    without that screen changing with them: `people` holds RMs and Admins
    only, `super_admins` the workspace's Super Admins. The rest is new and
    additive.
    """
    settings = get_settings()
    workspace_id = require_workspace_id()
    ws = (await session.execute(
        select(Workspace).where(Workspace.id == workspace_id))).scalars().one()
    members = (await session.execute(
        select(WorkspaceMember).order_by(
            WorkspaceMember.role, WorkspaceMember.email))).scalars().all()
    accounts = {
        u.email.lower(): u for u in
        (await session.execute(select(User))).scalars().all()
    }

    people, super_admins, seen = [], [], set()
    groups: dict = {}
    for m in members:
        groups.setdefault(m.added_by_email or CARRIED_OVER, []).append(m.email)
        if m.role is UserRole.SUPER_ADMIN:
            if m.active:
                super_admins.append(m.email)
            continue
        account = accounts.get(m.email)
        seen.add(m.email)
        people.append({
            "email": m.email,
            "name": m.name or (account.name if account else "") or m.email,
            "mobile": (account.mobile if account else "") or "",
            "role": m.role.value,
            "active": m.active,
            "registered": account is not None,
            "last_login": account.last_login_at.isoformat()
                          if account and account.last_login_at else None,
            "synchronized_at": None,
            "added_by": m.added_by_email,
        })

    is_eko = await workspace_service.is_eko(session, workspace_id)
    if is_eko:
        # People the Authorization sheet lists but who have not signed up
        # yet are still shown, exactly as before workspaces.
        listed = await workspace_service.sheet_super_admins(session) or set()
        for email in sorted(listed):
            if email not in super_admins:
                super_admins.append(email)
        sheet = await _sheet_people(session=session, user=user)
        for p in sheet["people"]:
            if p["role"] not in ("rm", "admin"):
                continue
            if (p["email"] or "").lower() not in seen:
                people.append({**p, "added_by": None})

    # A Super Admin is shown in the Owners box only — never also as an
    # old, inactive Admin row left behind in the sheet's history.
    owners = {e.lower() for e in super_admins}
    people = [p for p in people
              if not ((p["email"] or "").lower() in owners
                      and not p["active"])]

    return {
        "people": people,
        "total": len(people),
        "super_admins": super_admins,
        "source": ("Authorization Google Sheet and this app" if is_eko
                   else "Added in this app"),
        "sync_interval_minutes": settings.google_sheets_sync_interval_minutes,
        # New, additive.
        "workspace": {"id": str(ws.id), "name": ws.name},
        "by_super_admin": groups,
    }


@router.post("/grant", status_code=status.HTTP_201_CREATED)
async def grant_access(
    request: GrantRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Add someone to THIS workspace as a Super Admin, Admin or RM."""
    settings = get_settings()
    if not settings.email_domain_allowed(request.email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Only {settings.allowed_email_domains_text} addresses can be "
            f"given access.",
        )
    workspace_id = require_workspace_id()
    email = str(request.email).strip().lower()
    by = _who(user).lower()
    existing = (await session.execute(
        select(WorkspaceMember).where(WorkspaceMember.email == email)
    )).scalars().first()
    if existing is not None:
        action = "reactivated" if not existing.active else "updated"
        existing.active = True
        existing.role = _role(request.role)
        existing.name = request.name.strip() or existing.name
        existing.added_by_email = by
    else:
        action = "added"
        session.add(WorkspaceMember(
            workspace_id=workspace_id, email=email,
            name=request.name.strip(), role=_role(request.role),
            active=True, added_by_email=by,
        ))
    await session.commit()
    logger.info("access_router.grant_access: %s %s as %s by %s",
                email, action, request.role, by)

    answer = {"email": email, "role": request.role, "active": True,
              "action": action, "added_by": by}
    if (request.role in ("rm", "admin")
            and await workspace_service.is_eko(session, workspace_id)):
        try:
            await _grant_in_sheet(request=request, user=user)
            answer["sheet"] = "updated"
        except HTTPException as e:
            answer["sheet"] = "not updated"
            answer["sheet_note"] = e.detail
    return answer


@router.post("/revoke")
async def revoke_access(
    request: RevokeRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Remove someone's access to THIS workspace. Their record is kept."""
    email = str(request.email).strip().lower()
    if email == _who(user).lower():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "You cannot remove your own access.")
    workspace_id = require_workspace_id()
    member = (await session.execute(
        select(WorkspaceMember).where(WorkspaceMember.email == email)
    )).scalars().first()
    if member is None or not member.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"{email} is not an active member here.")
    if member.role is UserRole.SUPER_ADMIN:
        others = (await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.role == UserRole.SUPER_ADMIN,
                WorkspaceMember.active.is_(True),
                WorkspaceMember.email != email))).scalars().all()
        if not others:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This is the workspace's only Super Admin. Add another "
                "before removing them.")
    member.active = False
    await session.commit()
    logger.info("access_router.revoke_access: %s removed by %s",
                email, _who(user))

    answer = {"email": email, "role": member.role.value, "active": False,
              "action": "revoked"}
    if (member.role in (UserRole.RM, UserRole.ADMIN)
            and await workspace_service.is_eko(session, workspace_id)):
        try:
            await _revoke_in_sheet(
                request=RevokeRequest(email=email, role=member.role.value),
                session=session, user=user)
            answer["sheet"] = "updated"
        except HTTPException as e:
            answer["sheet"] = "not updated"
            answer["sheet_note"] = e.detail
    return answer
