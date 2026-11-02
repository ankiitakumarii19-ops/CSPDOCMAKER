"""
CSP DocMaker — RM Alerts API

What an RM is being asked to fix, and nothing else. Scoped the same way CSP
access is: an RM sees their own alerts plus every unowned one, and an Admin
monitors all of them read-only.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.rm_alert import OPEN, RMAlert
from app.services import csp_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertResponse(BaseModel):
    id: str
    csp_id: str
    kind: str
    message: str
    details: Optional[dict] = None
    rm_email: Optional[str] = None
    unassigned: bool
    created_at: str


class AlertListResponse(BaseModel):
    alerts: List[AlertResponse]
    total: int


@router.get("", response_model=AlertListResponse, summary="Open alerts for me")
async def list_alerts(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("rm", "admin", "super_admin")),
):
    """Open alerts this user should act on, newest first.

    Looked at again first (No. 174): a card whose details are all there now
    goes to History, so the count is only what is still pending."""
    from app.services import action_required, alert_service

    def _recheck(sync):
        mine = list(sync.execute(action_required.visible(
            select(RMAlert).where(RMAlert.status == OPEN), user)).scalars())
        return alert_service.recheck(sync, mine)

    if await session.run_sync(_recheck):
        await session.commit()

    query = select(RMAlert).where(RMAlert.status == OPEN)

    if not csp_access.is_admin(user):
        email = (user.get("sub") or "").strip().lower()
        # An unowned CSP's alert has no rm_email, and every RM may act on it.
        query = query.where(
            (RMAlert.rm_email == email) | (RMAlert.rm_email.is_(None))
        )

    result = await session.execute(query.order_by(RMAlert.created_at.desc()))
    alerts = result.scalars().all()

    return AlertListResponse(
        alerts=[
            AlertResponse(
                id=str(a.id),
                csp_id=a.csp_id,
                kind=a.kind,
                message=a.message,
                details=a.details,
                rm_email=a.rm_email,
                unassigned=a.rm_email is None,
                created_at=a.created_at.isoformat(),
            )
            for a in alerts
        ],
        total=len(alerts),
    )


# ---- No. 174: History, and one card opened -------------------------------

@router.get("/history", summary="Action Required: fixed and pending")
async def alert_history(
    show: str = "all",
    q: str = "",
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("rm", "admin", "super_admin")),
):
    """Fixed (with when and how) / Pending / All, searchable by name, code,
    phone or email."""
    from app.services import action_required

    if show not in ("all", "fixed", "pending"):
        show = "all"
    rows = await session.run_sync(
        lambda s: action_required.history(s, user, show, q[:100]))
    return {"items": rows, "total": len(rows)}


@router.get("/{alert_id}", summary="One Action Required card, in full")
async def alert_detail(
    alert_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("rm", "admin", "super_admin")),
):
    import uuid as _uuid

    from fastapi import HTTPException

    from app.services import action_required

    try:
        key = _uuid.UUID(alert_id)
    except ValueError:
        raise HTTPException(404, "No such item.")
    alert = await session.get(RMAlert, key)
    if alert is None or not action_required.may_see(alert, user):
        # The same answer whether it does not exist or is not theirs.
        raise HTTPException(404, "No such item.")
    return await session.run_sync(lambda s: action_required.detail(s, alert))

