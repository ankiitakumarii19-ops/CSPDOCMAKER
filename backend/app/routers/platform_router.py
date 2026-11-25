"""
CSP DocMaker — the Supreme Owner's console (No. 240, SaaS upgrade Stage 6)

The platform owner, above every workspace. Who: the emails in the server
setting SUPREME_OWNER_EMAILS (never a sheet, never a screen). A workspace's
own Super Admin ("Super Owner") is NOT a Supreme Owner and is refused here.

Counts, health and plans only: no route here returns a CSP's details, a
document, a photo, a message or anyone's look. (Brief: "administrative access
must not automatically grant unrestricted access to customer document
contents".)

  GET    /api/platform/overview                 totals + system health
  GET    /api/platform/workspaces               one row per workspace
  POST   /api/platform/workspaces/{id}/suspend     switch a workspace off
  POST   /api/platform/workspaces/{id}/reactivate  switch it on again
  PUT    /api/platform/workspaces/{id}/subscription  plan, status, trial...
  GET    /api/platform/plans  |  POST /api/platform/plans  |  PUT /api/platform/plans/{key}
  GET    /api/platform/announcements  |  POST  |  DELETE /api/platform/announcements/{id}
  GET    /api/me/platform        {"supreme_owner": bool} — for the menu
  GET    /api/me/announcements   banners for this workspace (every member)

Every change is audited (audit_logs, action platform_*).
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.dependencies import get_current_user
from app.models.audit_log import AuditLog
from app.models.platform import (SUBSCRIPTION_STATUSES, Plan, PlatformAnnouncement,
                                 WorkspaceSubscription)
from app.models.workspace import Workspace
from app.services import plan_limits
from app.workspace_context import all_workspaces, current_workspace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/platform", tags=["platform"])
me_router = APIRouter(prefix="/api/me", tags=["me"])

EKO_SLUG = "sbi-kiosk-csp"


def _email(user: dict) -> str:
    return ((user or {}).get("sub") or (user or {}).get("email") or "").strip().lower()


def is_supreme_owner(user: dict) -> bool:
    return _email(user) in get_settings().server.supreme_owners


async def supreme_owner(user=Depends(get_current_user)) -> dict:
    if not is_supreme_owner(user):
        logger.warning("platform_router: %s was refused the Supreme Owner console",
                       _email(user) or "someone")
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the platform's Supreme Owner may open this.")
    return user


def _audit(session, user, action: str, resource: str, detail: dict) -> None:
    session.add(AuditLog(workspace_id=current_workspace_id(), action=action,
                         resource_type="platform", resource_id=resource,
                         result="success", metadata_json={"by": _email(user), **detail}))


# ---- reading ----------------------------------------------------------------

async def _health(session) -> dict:
    out = {"database": "ok"}
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(get_settings().server.redis_url, socket_connect_timeout=2)
        try:
            await r.ping()
            out["queue"] = "ok"
        finally:
            await r.aclose()
    except Exception as e:
        out["queue"] = f"problem: {type(e).__name__}"
        logger.warning("platform_router: the queue (Redis) did not answer: %s: %s",
                       type(e).__name__, e)
    try:
        from app.services import alerts
        problem = alerts.backup_problem(get_settings().server, datetime.now(timezone.utc))
        out["backup"] = "ok" if problem is None else f"problem: {problem.title}"
    except Exception as e:
        out["backup"] = f"unknown: {type(e).__name__}"
    return out


async def _per_workspace(session) -> list:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    with all_workspaces():
        spaces = (await session.execute(select(Workspace).order_by(Workspace.created_at))).scalars().all()
        subs = {s.workspace_id: s for s in (await session.execute(select(WorkspaceSubscription))).scalars()}
        plans = {p.key: p for p in (await session.execute(select(Plan))).scalars()}
        used = await plan_limits.usage(session)
        rows = (await session.execute(text("""
            SELECT w.id,
              (SELECT status FROM sync_runs s WHERE s.workspace_id = w.id AND s.source = 'csp'
                 ORDER BY s.started_at DESC LIMIT 1) AS last_sync,
              (SELECT count(*) FROM whatsapp_messages m WHERE m.workspace_id = w.id
                 AND m.created_at >= :t AND m.send_status = 'failed') AS wa_failed,
              (SELECT count(*) FROM whatsapp_messages m WHERE m.workspace_id = w.id
                 AND m.created_at >= :t) AS wa_all,
              (SELECT count(*) FROM email_messages e WHERE e.workspace_id = w.id
                 AND e.created_at >= :t AND e.send_status = 'failed') AS mail_failed,
              (SELECT count(*) FROM processing_jobs j WHERE j.workspace_id = w.id
                 AND j.current_state IN ('FAILED_DOCUMENT_GENERATION', 'FAILED_PDF_CONVERSION'))
                 AS gen_failed
            FROM workspaces w
        """), {"t": since})).all()
    health = {str(r[0]): {"last_sheet_read": r[1] or "never", "whatsapp_failed_24h": int(r[2]),
                          "whatsapp_24h": int(r[3]), "email_failed_24h": int(r[4]),
                          "failed_generations": int(r[5])} for r in rows}
    out = []
    for ws in spaces:
        sub = subs.get(ws.id)
        plan = plans.get(sub.plan_key) if sub else None
        out.append({
            "id": str(ws.id), "name": ws.name, "slug": ws.slug, "active": ws.active,
            "is_eko": ws.slug == EKO_SLUG, "owner_email": ws.owner_email,
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
            "usage": used.get(str(ws.id), {}),
            "health": health.get(str(ws.id), {}),
            "subscription": None if sub is None else {
                "plan_key": sub.plan_key, "plan_name": plan.name if plan else sub.plan_key,
                "status": sub.status,
                "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
                "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
                "payment_provider": sub.payment_provider, "white_label": sub.white_label,
                "custom_domain": sub.custom_domain, "notes": sub.notes,
                "limits": None if plan is None else {
                    "max_documents_month": plan.max_documents_month,
                    "max_storage_mb": plan.max_storage_mb, "max_users": plan.max_users},
            },
        })
    return out


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_session), user=Depends(supreme_owner)):
    spaces = await _per_workspace(session)
    with all_workspaces():
        people = int((await session.execute(text(
            "SELECT count(DISTINCT lower(m.email)) FROM workspace_members m "
            "JOIN workspaces w ON w.id = m.workspace_id WHERE m.active"))).scalar() or 0)
    total = lambda key: sum(s["usage"].get(key, 0) for s in spaces)  # noqa: E731
    return {
        "workspaces": len(spaces),
        "active_workspaces": sum(1 for s in spaces if s["active"]),
        "inactive_workspaces": sum(1 for s in spaces if not s["active"]),
        "people": people,
        "documents": total("documents"),
        "documents_this_month": total("documents_this_month"),
        "failed_generations": sum(s["health"].get("failed_generations", 0) for s in spaces),
        "storage_bytes": total("storage_bytes"),
        "whatsapp_failed_24h": sum(s["health"].get("whatsapp_failed_24h", 0) for s in spaces),
        "email_failed_24h": sum(s["health"].get("email_failed_24h", 0) for s in spaces),
        "health": await _health(session),
    }


@router.get("/workspaces")
async def workspaces(session: AsyncSession = Depends(get_session), user=Depends(supreme_owner)):
    return {"workspaces": await _per_workspace(session)}


# ---- workspaces: suspend, reactivate, plan -----------------------------------

async def _workspace(session, workspace_id: str) -> Workspace:
    try:
        wid = uuid.UUID(workspace_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such workspace.")
    with all_workspaces():
        ws = await session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such workspace.")
    return ws


@router.post("/workspaces/{workspace_id}/suspend")
async def suspend(workspace_id: str, session: AsyncSession = Depends(get_session),
                  user=Depends(supreme_owner)):
    ws = await _workspace(session, workspace_id)
    if ws.slug == EKO_SLUG:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The original workspace (Eko) cannot be suspended here.")
    if ws.id == current_workspace_id():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "You are signed in to this workspace; suspending it would lock you out.")
    ws.active = False
    _audit(session, user, "platform_suspend", str(ws.id), {"workspace": ws.name})
    await session.commit()
    logger.info("platform_router: %s suspended workspace %s (%s)", _email(user), ws.name, ws.id)
    return {"id": str(ws.id), "active": False}


@router.post("/workspaces/{workspace_id}/reactivate")
async def reactivate(workspace_id: str, session: AsyncSession = Depends(get_session),
                     user=Depends(supreme_owner)):
    ws = await _workspace(session, workspace_id)
    ws.active = True
    _audit(session, user, "platform_reactivate", str(ws.id), {"workspace": ws.name})
    await session.commit()
    logger.info("platform_router: %s reactivated workspace %s (%s)", _email(user), ws.name, ws.id)
    return {"id": str(ws.id), "active": True}


class SubscriptionIn(BaseModel):
    plan_key: str = Field(min_length=1, max_length=40)
    status: str = "active"
    trial_ends_at: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    white_label: bool = False
    custom_domain: Optional[str] = Field(default=None, max_length=253)
    notes: Optional[str] = Field(default=None, max_length=2000)


DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


@router.put("/workspaces/{workspace_id}/subscription")
async def set_subscription(workspace_id: str, body: SubscriptionIn,
                           session: AsyncSession = Depends(get_session),
                           user=Depends(supreme_owner)):
    ws = await _workspace(session, workspace_id)
    if body.status not in SUBSCRIPTION_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Status: one of {', '.join(SUBSCRIPTION_STATUSES)}.")
    domain = (body.custom_domain or "").strip().lower() or None
    if domain and not DOMAIN.match(domain):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{domain!r} is not a domain name.")
    with all_workspaces():
        plan = await session.get(Plan, body.plan_key)
        if plan is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"There is no plan {body.plan_key!r}.")
        if ws.slug == EKO_SLUG and (body.plan_key != "unlimited" or body.status != "unlimited"):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "The original workspace (Eko) stays on Unlimited: no limits on Eko.")
        sub = await session.get(WorkspaceSubscription, ws.id)
        before = None if sub is None else {"plan": sub.plan_key, "status": sub.status}
        if sub is None:
            sub = WorkspaceSubscription(workspace_id=ws.id, plan_key=plan.key)
            session.add(sub)
        sub.plan_key, sub.status = plan.key, body.status
        sub.trial_ends_at, sub.current_period_end = body.trial_ends_at, body.current_period_end
        sub.white_label, sub.custom_domain, sub.notes = body.white_label, domain, body.notes
        sub.updated_by = _email(user)
        _audit(session, user, "platform_subscription", str(ws.id),
               {"workspace": ws.name, "before": before,
                "after": {"plan": plan.key, "status": body.status}})
        await session.commit()
    logger.info("platform_router: %s put %s on %s (%s)", _email(user), ws.name, plan.key, body.status)
    return {"workspaces": await _per_workspace(session)}


# ---- plans ---------------------------------------------------------------------

class PlanIn(BaseModel):
    key: Optional[str] = Field(default=None, max_length=40)
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)
    price_monthly_paise: Optional[int] = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    max_documents_month: Optional[int] = Field(default=None, ge=0)
    max_storage_mb: Optional[int] = Field(default=None, ge=0)
    max_users: Optional[int] = Field(default=None, ge=0)
    trial_days: Optional[int] = Field(default=None, ge=0, le=365)
    active: bool = True


def _plan_view(p: Plan) -> dict:
    return {"key": p.key, "name": p.name, "description": p.description,
            "price_monthly_paise": p.price_monthly_paise, "currency": p.currency,
            "max_documents_month": p.max_documents_month, "max_storage_mb": p.max_storage_mb,
            "max_users": p.max_users, "trial_days": p.trial_days, "active": p.active}


@router.get("/plans")
async def plans(session: AsyncSession = Depends(get_session), user=Depends(supreme_owner)):
    rows = (await session.execute(select(Plan).order_by(Plan.created_at))).scalars().all()
    return {"plans": [_plan_view(p) for p in rows],
            "payment_gateway": "none — prices are for information; nothing is charged"}


@router.post("/plans", status_code=status.HTTP_201_CREATED)
async def create_plan(body: PlanIn, session: AsyncSession = Depends(get_session),
                      user=Depends(supreme_owner)):
    key = re.sub(r"[^a-z0-9]+", "_", (body.key or body.name).lower()).strip("_")[:40]
    if not key or await session.get(Plan, key) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"There is already a plan {key!r}.")
    plan = Plan(key=key, **body.model_dump(exclude={"key"}))
    plan.currency = plan.currency.upper()
    session.add(plan)
    _audit(session, user, "platform_plan_create", key, {"plan": _plan_view(plan)})
    await session.commit()
    return _plan_view(plan)


@router.put("/plans/{key}")
async def change_plan(key: str, body: PlanIn, session: AsyncSession = Depends(get_session),
                      user=Depends(supreme_owner)):
    plan = await session.get(Plan, key)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"There is no plan {key!r}.")
    if key == "unlimited" and any(getattr(body, f) for f in (
            "max_documents_month", "max_storage_mb", "max_users")):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The Unlimited plan has no limits (Eko is on it).")
    before = _plan_view(plan)
    for field, value in body.model_dump(exclude={"key"}).items():
        setattr(plan, field, value)
    plan.currency = plan.currency.upper()
    _audit(session, user, "platform_plan_change", key, {"before": before, "after": _plan_view(plan)})
    await session.commit()
    return _plan_view(plan)


# ---- announcements ---------------------------------------------------------------

class AnnouncementIn(BaseModel):
    message: str = Field(min_length=3, max_length=500)
    level: str = "info"
    workspace_id: Optional[str] = None     # None = every workspace
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


def _announcement_view(a: PlatformAnnouncement) -> dict:
    return {"id": str(a.id), "message": a.message, "level": a.level,
            "workspace_id": str(a.target_workspace_id) if a.target_workspace_id else None,
            "starts_at": a.starts_at.isoformat() if a.starts_at else None,
            "ends_at": a.ends_at.isoformat() if a.ends_at else None,
            "active": a.active, "created_by": a.created_by,
            "created_at": a.created_at.isoformat() if a.created_at else None}


@router.get("/announcements")
async def announcements(session: AsyncSession = Depends(get_session), user=Depends(supreme_owner)):
    rows = (await session.execute(select(PlatformAnnouncement)
                                  .order_by(PlatformAnnouncement.created_at.desc()))).scalars().all()
    return {"announcements": [_announcement_view(a) for a in rows]}


@router.post("/announcements", status_code=status.HTTP_201_CREATED)
async def create_announcement(body: AnnouncementIn, session: AsyncSession = Depends(get_session),
                              user=Depends(supreme_owner)):
    if body.level not in ("info", "warning"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Level: info or warning.")
    target = None
    if body.workspace_id:
        target = (await _workspace(session, body.workspace_id)).id
    if body.starts_at and body.ends_at and body.ends_at <= body.starts_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "It must end after it starts.")
    a = PlatformAnnouncement(message=" ".join(body.message.split()), level=body.level,
                             target_workspace_id=target, starts_at=body.starts_at,
                             ends_at=body.ends_at, created_by=_email(user))
    session.add(a)
    _audit(session, user, "platform_announce", str(target or "all"), {"message": a.message})
    await session.commit()
    return _announcement_view(a)


@router.delete("/announcements/{announcement_id}")
async def end_announcement(announcement_id: str, session: AsyncSession = Depends(get_session),
                           user=Depends(supreme_owner)):
    try:
        aid = uuid.UUID(announcement_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such announcement.")
    a = await session.get(PlatformAnnouncement, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such announcement.")
    a.active = False
    _audit(session, user, "platform_announce_end", str(a.id), {})
    await session.commit()
    return _announcement_view(a)


# ---- for every signed-in person -------------------------------------------------

@me_router.get("/platform")
async def am_i_supreme_owner(user=Depends(get_current_user)):
    return {"supreme_owner": is_supreme_owner(user)}


@me_router.get("/announcements")
async def my_announcements(session: AsyncSession = Depends(get_session),
                           user=Depends(get_current_user)):
    from sqlalchemy import or_
    now = datetime.now(timezone.utc)
    ws = current_workspace_id()
    rows = (await session.execute(select(PlatformAnnouncement).where(
        PlatformAnnouncement.active.is_(True),
        or_(PlatformAnnouncement.target_workspace_id.is_(None),
            PlatformAnnouncement.target_workspace_id == ws),
        or_(PlatformAnnouncement.starts_at.is_(None), PlatformAnnouncement.starts_at <= now),
        or_(PlatformAnnouncement.ends_at.is_(None), PlatformAnnouncement.ends_at > now),
    ).order_by(PlatformAnnouncement.created_at.desc()).limit(3))).scalars().all()
    return {"announcements": [{"id": str(a.id), "message": a.message, "level": a.level}
                              for a in rows]}
