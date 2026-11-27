"""
CSP DocMaker — the RM dashboard (PROJECT-REGISTER No. 234)

  GET /api/rm-dashboard/pending      CSPs still waiting for documents, how
                                     many times each was contacted, counts,
                                     a per-RM / DC / state / district table
                                     and the values each filter can take
  GET /api/rm-dashboard/pending.csv  the same list (every row), as a file

For RMs, Admins and the Super Admin; every CSP, whoever its RM is (No. 234).
The rules are in services/pending_documents.py.
"""

import csv
import io
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_any_role
from app.services import pending_documents as pd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rm-dashboard", tags=["RM dashboard"])


async def _rows(session, rm, dc, state, district, contacted, hold, q, sort,
                date_from=None, date_to=None):
    from app.services import india_days

    try:
        contacted = pd.check("contacted", contacted, pd.CONTACT_BANDS)
        hold = pd.check("hold", hold, pd.HOLD_VIEWS)
        sort = pd.check("sort", sort, pd.SORTS) or "contacts"
        # No. 272: the day each CSP was last contacted, in India time.
        last_on = india_days.bounds(date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    filters = {"rm": rm, "dc": dc, "state": state, "district": district}
    try:
        data = await session.run_sync(pd.load)
    except Exception as exc:
        error_id = uuid.uuid4().hex[:12]
        logger.exception("rm_dashboard: reading the CSPs failed "
                         "(error_id=%s): %s: %s", error_id,
                         type(exc).__name__, exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"The dashboard could not be read (error {error_id}).")
    everyone = data["rows"]
    shown = pd.sort_rows(pd.last_contacted_in(
        pd.apply(everyone, filters, contacted, hold, q), last_on), sort)
    return data, everyone, shown, filters


@router.get("/pending", summary="CSPs still waiting for their documents")
async def pending(
    rm: str | None = None,
    dc: str | None = None,
    state: str | None = None,
    district: str | None = None,
    contacted: str | None = None,
    hold: str | None = None,
    q: str | None = Query(None, max_length=100),
    sort: str | None = None,
    date_from: str | None = Query(
        None, description="Last contacted on or after this India day (YYYY-MM-DD)"),
    date_to: str | None = Query(
        None, description="Last contacted on or before this India day (YYYY-MM-DD)"),
    group_by: str = "rm",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    if group_by not in pd.GROUPS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"group_by is one of {', '.join(pd.GROUPS)}.")
    data, everyone, shown, filters = await _rows(
        session, rm, dc, state, district, contacted, hold, q, sort,
        date_from, date_to)
    start = (page - 1) * page_size
    return {
        "summary": pd.summary(shown),
        "all_left": len(everyone),
        "old_not_listed": data["old_not_listed"],
        "groups": pd.grouped(shown, group_by),
        "group_by": group_by,
        "options": pd.options(everyone, filters),
        "total": len(shown),
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-len(shown) // page_size)),
        "csps": shown[start:start + page_size],
    }


@router.get("/pending.csv", summary="The same list, as a CSV file")
async def pending_csv(
    rm: str | None = None,
    dc: str | None = None,
    state: str | None = None,
    district: str | None = None,
    contacted: str | None = None,
    hold: str | None = None,
    q: str | None = Query(None, max_length=100),
    sort: str | None = None,
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_any_role),
):
    _, _, shown, _ = await _rows(
        session, rm, dc, state, district, contacted, hold, q, sort,
        date_from, date_to)
    columns = [("csp_id", "CSP ID"), ("name", "Name"), ("mobile", "Mobile"),
               ("rm", "RM"), ("dc", "DC"), ("state", "State"),
               ("district", "District"), ("documents_left", "Documents left"),
               ("whatsapp", "WhatsApps sent"), ("email", "Emails sent"),
               ("contacts", "Times contacted"),
               ("last_contacted", "Last contacted"), ("on_hold", "On hold")]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([title for _, title in columns])
    for row in shown:
        writer.writerow([", ".join(row[k]) if isinstance(row[k], list)
                         else ("" if row[k] is None else row[k])
                         for k, _ in columns])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    logger.info("rm_dashboard.pending_csv: %s exported %d row(s)",
                user.get("sub"), len(shown))
    return StreamingResponse(
        iter([buffer.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="csps-documents-left-{stamp}.csv"'})
