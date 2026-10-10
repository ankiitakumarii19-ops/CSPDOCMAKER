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
    """Open alerts this user should act on, newest first."""
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
