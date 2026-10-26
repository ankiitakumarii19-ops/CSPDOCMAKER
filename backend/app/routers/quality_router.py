"""
CSP DocMaker — data quality: auto-filled values and sheet freshness (No. 146)

  * GET /api/quality/freshness           — every signed-in role: when each
    sheet the app reads was last read fully, and whether that is on time.
    The reason a read failed is shown to Admins and Super Admins only.
  * GET /api/admin/quality/scoreboard    — Admin + Super Admin: per field
    and source, how many auto-filled values people kept or corrected.
  * GET /api/admin/quality/corrections   — Admin + Super Admin: the
    corrections themselves, newest first.

Read-only. Everything is computed from field_provenance, field_corrections
and sync_runs (services/field_quality.py).
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.dependencies import require_any_role, require_role
from app.services import field_quality

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quality"])

ADMINS = ("admin", "super_admin")


@router.get("/api/quality/freshness",
            summary="When each sheet was last read, and whether that is on time")
async def freshness(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    with_errors = (user.get("role") or "").lower() in ADMINS
    badges = await session.run_sync(
        lambda s: field_quality.freshness(s, get_settings(),
                                          with_errors=with_errors))
    return {"sources": badges}


@router.get("/api/admin/quality/scoreboard",
            summary="How many auto-filled values people kept or corrected")
async def scoreboard(
    weeks: int = Query(8, ge=1, le=52),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    return await session.run_sync(field_quality.scoreboard, weeks)


@router.get("/api/admin/quality/corrections",
            summary="Every correction to an auto-filled value, newest first")
async def corrections(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    field: str = Query("", max_length=50),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    return await session.run_sync(field_quality.recent_corrections, limit,
                                  offset, field)
