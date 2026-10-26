"""
CSP DocMaker — data quality: auto-filled values and sheet freshness (No. 146)

  * GET /api/quality/freshness           — every signed-in role: when each
    sheet the app reads was last read fully, and whether that is on time.
    The reason a read failed is shown to Admins and Super Admins only.
  * GET /api/admin/quality/harness       — Admin + Super Admin: how the app
    checks itself (No. 149), one row per check with where it stands.
  * GET /api/admin/quality/scoreboard    — Admin + Super Admin: per field
    and source, how many auto-filled values people kept or corrected.
  * GET /api/admin/quality/corrections   — Admin + Super Admin: the
    corrections themselves, newest first.
  * GET  /api/admin/quality/values           — the auto-filled values, and
    POST /api/admin/quality/values/confirm   — "this one is right" (marks it
                                               checked; writes nothing), or
    POST /api/admin/quality/values/correct   — the right value: written to
    the CSP sheet exactly as the sheet editor writes it, then recorded as a
    correction by this person. Refused (409) when the value changed since
    the page showed it. Admin + Super Admin; audited.

Computed from field_provenance, field_corrections and sync_runs
(services/field_quality.py).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.dependencies import require_any_role, require_role
from app.services import field_quality

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quality"])

ADMINS = ("admin", "super_admin")


def _who(user) -> str:
    return (user or {}).get("sub") or (user or {}).get("email") or "unknown"


class ValueIn(BaseModel):
    csp_id: str = Field(min_length=1, max_length=100)
    field: str = Field(min_length=1, max_length=50)
    # What the page showed: a value changed since is not overwritten.
    current_value: str = Field(default="", max_length=5000)


class CorrectionIn(ValueIn):
    new_value: str = Field(min_length=1, max_length=5000)


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


@router.get("/api/admin/quality/harness",
            summary="How the app checks itself, and where each check stands")
async def harness(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    rows = await session.run_sync(
        lambda s: field_quality.harness(s, get_settings()))
    return {"checks": rows}


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


@router.get("/api/admin/quality/values",
            summary="The auto-filled values, unchecked first")
async def values(
    status_: str = Query("", alias="status",
                         pattern="^(|auto|confirmed|corrected|withdrawn)$"),
    field: str = Query("", max_length=50),
    q: str = Query("", max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    return await session.run_sync(field_quality.list_values, status_, field,
                                  q, limit, offset)


async def _checked(session: AsyncSession, body: ValueIn):
    """The value as the page showed it, or a clear refusal."""
    from sqlalchemy import select

    from app.models.field_provenance import FieldProvenance
    p = (await session.execute(select(FieldProvenance).where(
        FieldProvenance.csp_id == body.csp_id,
        FieldProvenance.field == body.field))).scalar_one_or_none()
    if p is None or p.status == "withdrawn":
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "The app has no filled value for that CSP and "
                            "field.")
    if field_quality.norm(body.current_value) != p.current_value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This value changed since the page was opened (it is now "
            f"{p.current_value!r}). Reload and check it again.")
    return p


async def _audit(session: AsyncSession, user, action: str, body: ValueIn,
                 extra: dict) -> None:
    from app.models.audit_log import AuditLog
    session.add(AuditLog(
        action=action, resource_type="csp", resource_id=body.csp_id,
        csp_id=body.csp_id, result="success",
        metadata_json={"by": _who(user), "field": body.field, **extra}))


@router.post("/api/admin/quality/values/confirm",
             summary="Mark an auto-filled value as checked and right")
async def confirm_value(
    body: ValueIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    p = await _checked(session, body)
    if p.status == "auto":
        await session.run_sync(field_quality.record_check, body.csp_id,
                               {body.field: p.current_value}, "data_quality",
                               _who(user))
        await _audit(session, user, "data_quality_confirm", body,
                     {"value": p.current_value})
        await session.commit()
        logger.info("quality_router: %s confirmed %s %s", _who(user),
                    body.csp_id, body.field)
    return await session.run_sync(field_quality.value_row, body.csp_id,
                                  body.field)


@router.post("/api/admin/quality/values/correct",
             summary="Correct an auto-filled value in the CSP sheet")
async def correct_value(
    body: CorrectionIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    from sqlalchemy import select

    from app.models.csp_record import CSPRecord
    from app.services import csp_mapping
    from app.services import sheet_writeback_service as wb

    p = await _checked(session, body)
    new = field_quality.norm(body.new_value)
    if not new:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A blank cannot replace a value.")
    if new == p.current_value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "That is the value already there — use Confirm.")
    if body.field in field_quality.NOT_EDITABLE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            field_quality.NOT_EDITABLE[body.field])
    if body.field not in csp_mapping.FIELD_TO_SHEET_COLUMN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "The CSP sheet has no column for this field.")

    # The sheet is the source of truth: a value set only here would be
    # put back by the next sync. Written exactly as the CSP's form writes.
    try:
        written, skipped = wb.write_values(body.csp_id, {body.field: new})
    except wb.SheetWriteError as e:
        logger.error("quality_router: %s could not correct %s %s in the "
                     "sheet: %s", _who(user), body.csp_id, body.field, e)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"The CSP sheet could not be updated, so nothing "
                            f"was changed: {e}")
    if body.field not in written:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "The CSP sheet has no column for this field, so "
                            "nothing was changed.")

    record = (await session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == body.csp_id))).scalar_one_or_none()
    if record is not None:
        setattr(record, body.field, new)   # the sync agrees next run
    before = p.current_value
    await session.run_sync(field_quality.record_check, body.csp_id,
                           {body.field: new}, "data_quality", _who(user))
    await _audit(session, user, "data_quality_correct", body,
                 {"from": before, "to": new})
    await session.commit()
    logger.info("quality_router: %s corrected %s %s in the sheet",
                _who(user), body.csp_id, body.field)
    return await session.run_sync(field_quality.value_row, body.csp_id,
                                  body.field)


# ---- the feedback loops (No. 150) ---------------------------------------

@router.get("/api/admin/quality/suggestions",
            summary="Loop 1: suggested INFO fixes from repeated corrections")
async def suggestions(
    status_: str = Query("", alias="status",
                         pattern="^(|open|accepted|fixed|dismissed)$"),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    from app.services import feedback_loops

    def work(s):
        feedback_loops.refresh_suggestions(
            s, get_settings().quality_suggest_min_csps)
        return feedback_loops.list_suggestions(s, status_)
    rows = await session.run_sync(work)
    await session.commit()
    return {"suggestions": rows,
            "min_csps": get_settings().quality_suggest_min_csps}


@router.post("/api/admin/quality/suggestions/{suggestion_id}/{action}",
             summary="Accept (the team fixes INFO) or dismiss a suggestion")
async def decide_suggestion(
    suggestion_id: str,
    action: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    import uuid as _uuid

    from app.models.audit_log import AuditLog
    from app.services import feedback_loops

    if action not in ("accept", "dismiss"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "The action is accept or dismiss.")
    try:
        key = _uuid.UUID(suggestion_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such suggestion.")
    s = await session.run_sync(feedback_loops.decide, key, action, _who(user))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such suggestion.")
    session.add(AuditLog(
        action=f"info_suggestion_{action}", resource_type="quality_suggestion",
        resource_id=suggestion_id, result="success",
        metadata_json={"by": _who(user), "field": s.field, "rule": s.rule,
                       "from": s.from_value, "to": s.to_value}))
    await session.commit()
    logger.info("quality_router: %s %sed INFO suggestion %s (%s %r -> %r)",
                _who(user), action, suggestion_id, s.field, s.from_value,
                s.to_value)
    return {"id": suggestion_id, "status": s.status}


@router.get("/api/admin/quality/contact-fixes",
            summary="Loop 2: bad numbers / bounced emails and what was done")
async def contact_fixes(
    status_: str = Query("", alias="status",
                         pattern="^(|open|asked|corrected|resent|done|stopped)$"),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role(*ADMINS)),
):
    from app.services import feedback_loops
    return await session.run_sync(feedback_loops.list_contact_fixes, status_)
