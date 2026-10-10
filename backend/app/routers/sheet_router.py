"""
CSP DocMaker — the sheets behind the system, for a Super Admin

Every screen in this product is a view of records that came from a sheet.
This is the sheet itself: the tabs it has, the rows in them, and the
ability to correct, add or remove one without leaving the application.

Super Admin only, and deliberately. An Admin configures how the system
behaves; this changes the data every other screen is derived from, and the
two are different jobs. It is also the one place in the product where a
single click destroys something no amount of code can bring back, which is
a second reason to keep the door narrow.

Everything written here goes to the spreadsheet itself. There is no copy
and no queue: a correction made on this screen is visible to anyone with
the Google Sheet open a moment later, and will be read by the next sync.
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.dependencies import require_role
from app.models.data_source import PURPOSES, SOURCE_KINDS, DataSource
from app.services import sheet_admin_service as sheets
from app.services.sheet_admin_service import SheetAdminError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/sheets", tags=["sheets"])

# What a Photo cell is allowed to point at.
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


def _who(user) -> str:
    """The person acting, for the log. The token carries `sub`, not `email`."""
    return (user or {}).get("sub") or (user or {}).get("email") or "unknown"


# ---- what comes in ------------------------------------------------------

class RowIn(BaseModel):
    cells: Dict[str, str] = Field(default_factory=dict)


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    spreadsheet_id: str = Field(min_length=10, max_length=200)
    tab: str = Field(min_length=1, max_length=200)
    purpose: str = "records"
    kind: str = "google_sheet"


class SourcePatch(BaseModel):
    name: Optional[str] = None
    spreadsheet_id: Optional[str] = None
    tab: Optional[str] = None
    active: Optional[bool] = None


class TabIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    columns: Optional[List[str]] = None


# ---- helpers ------------------------------------------------------------

def _out(source: DataSource, tabs=None) -> dict:
    connection = source.connection or {}
    return {
        "id": str(source.id),
        "name": source.name,
        "kind": source.kind,
        "purpose": source.purpose,
        "active": source.active,
        "spreadsheet_id": connection.get("spreadsheet_id", ""),
        # One source names a single tab; the Authorization source names
        # several, so both shapes are reported rather than flattened.
        "tab": connection.get("tab", ""),
        "tabs_configured": connection.get("tabs") or (
            [connection.get("tab")] if connection.get("tab") else []),
        "last_status": source.last_status,
        "last_error": source.last_error,
        "tabs_live": tabs,
    }


async def _source(session: AsyncSession, source_id: str) -> DataSource:
    found = (await session.execute(
        select(DataSource).where(DataSource.id == source_id)
    )).scalars().first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No such sheet is registered.")
    return found


def _spreadsheet(source: DataSource) -> str:
    spreadsheet_id = (source.connection or {}).get("spreadsheet_id")
    if not spreadsheet_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{source.name!r} has no spreadsheet id configured.")
    return spreadsheet_id


# ---- the sheets themselves ----------------------------------------------

@router.get("/_photo")
async def sheet_photo(
    path: str,
    user=Depends(require_role("super_admin")),
):
    """The photograph a Photo cell names, as an image.

    The sheet stores a file path, which is the right thing for the document
    generator and useless to a person reading the screen. This serves the
    picture so the column shows a face instead of `C:\\...\\1A850076.jpg`.

    The path arrives from a spreadsheet cell, which anyone with the sheet
    can edit — so it is resolved and checked to be inside the photos
    directory before anything is opened. Without that, a cell reading
    `..\\..\\.env` would be a way to read any file on the server through
    this endpoint.
    """
    import os

    from fastapi.responses import FileResponse

    settings = get_settings()
    root = os.path.realpath(
        os.path.join(settings.document_output_dir, "photos"))
    wanted = os.path.realpath(path)

    if os.path.commonpath([root, wanted]) != root:
        logger.warning(
            "sheet_router.sheet_photo: refused a path outside the photos "
            "directory: %r (asked by %s)", path, _who(user))
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That path is not inside the photos directory.")

    if os.path.splitext(wanted)[1].lower() not in IMAGE_SUFFIXES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "That is not an image file.")
    if not os.path.isfile(wanted):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No photograph at that path.")

    return FileResponse(wanted)


@router.get("")
async def list_sheets(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Every registered sheet, with the tabs it actually has right now.

    The tab list is read from the spreadsheet on every call, so a tab added
    or deleted in Google Sheets shows up here without anything having to be
    told about it. A spreadsheet that cannot be opened reports why instead
    of disappearing from the list.
    """
    sources = (await session.execute(
        select(DataSource).order_by(DataSource.purpose, DataSource.name)
    )).scalars().all()

    # Two sources share one spreadsheet, so asking per source meant asking
    # Google the same question twice — and asking for the title separately
    # doubled it again: six round trips to describe three sources. One call
    # per DISTINCT spreadsheet instead.
    #
    # Sequential, deliberately. The Google client is built once and shared,
    # and its httplib2 transport is not thread-safe: fetching them at the
    # same time returned empty tab lists and, once, took a minute.
    described: Dict[str, tuple] = {}
    for source in sources:
        spreadsheet_id = (source.connection or {}).get("spreadsheet_id")
        if not spreadsheet_id or spreadsheet_id in described:
            continue
        try:
            described[spreadsheet_id] = (sheets.describe(spreadsheet_id), None)
        except SheetAdminError as e:
            described[spreadsheet_id] = (None, str(e))

    out = []
    for source in sources:
        spreadsheet_id = (source.connection or {}).get("spreadsheet_id")
        meta, error = described.get(spreadsheet_id, (None, None))
        payload = _out(source, meta["tabs"] if meta else None)
        payload["title"] = meta["title"] if meta else ""
        payload["error"] = error
        out.append(payload)
    return {"sheets": out}


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_sheet(
    body: SourceIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Add another sheet for this workspace to read."""
    if body.kind not in SOURCE_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown kind. Choose from: "
                            f"{', '.join(SOURCE_KINDS)}.")
    if body.purpose not in PURPOSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown purpose. Choose from: "
                            f"{', '.join(PURPOSES)}.")

    # Refused now rather than at the next sync: a sheet that cannot be
    # opened is a typo in the id, and saying so here is far cheaper than
    # a failed sync at three in the morning.
    try:
        tabs = sheets.list_tabs(body.spreadsheet_id)
    except SheetAdminError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if not any(t["title"] == body.tab for t in tabs):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"That spreadsheet has no tab called {body.tab!r}. It has: "
            f"{', '.join(t['title'] for t in tabs)}.")

    source = DataSource(
        name=body.name, kind=body.kind, purpose=body.purpose,
        connection={"spreadsheet_id": body.spreadsheet_id, "tab": body.tab},
        column_map={},
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    logger.info("sheet_router.register_sheet: %r added by %s",
                body.name, _who(user))
    return _out(source, tabs)


@router.patch("/{source_id}")
async def update_sheet(
    source_id: str,
    body: SourcePatch,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    source = await _source(session, source_id)
    connection = dict(source.connection or {})
    if body.name is not None:
        source.name = body.name
    if body.spreadsheet_id is not None:
        connection["spreadsheet_id"] = body.spreadsheet_id
    if body.tab is not None:
        connection["tab"] = body.tab
    if body.active is not None:
        source.active = body.active
    source.connection = connection
    await session.commit()
    await session.refresh(source)
    logger.info("sheet_router.update_sheet: %r changed by %s",
                source.name, _who(user))
    return _out(source)


@router.delete("/{source_id}")
async def unregister_sheet(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Stop reading a sheet. The spreadsheet itself is untouched."""
    source = await _source(session, source_id)
    name = source.name
    await session.delete(source)
    await session.commit()
    logger.info("sheet_router.unregister_sheet: %r removed by %s",
                name, _who(user))
    return {"removed": name,
            "note": "The spreadsheet itself was not changed; this system "
                    "has simply stopped reading it."}


# ---- rows ---------------------------------------------------------------

@router.get("/{source_id}/tabs/{tab}")
async def read_rows(
    source_id: str,
    tab: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """One tab's header and rows, each with its number in the spreadsheet."""
    source = await _source(session, source_id)
    try:
        return sheets.read_tab(_spreadsheet(source), tab)
    except SheetAdminError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.patch("/{source_id}/tabs/{tab}/rows/{row_number}")
async def update_row(
    source_id: str,
    tab: str,
    row_number: int,
    body: RowIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Change cells on one row. Written straight to the spreadsheet."""
    source = await _source(session, source_id)
    try:
        written, unknown = sheets.update_row(
            _spreadsheet(source), tab, row_number, body.cells)
    except SheetAdminError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    logger.info("sheet_router.update_row: %s row %d changed by %s (%s)",
                tab, row_number, _who(user), ", ".join(sorted(written)))
    return {"row_number": row_number, "written": written,
            "unknown_columns": unknown}


@router.post("/{source_id}/tabs/{tab}/rows",
             status_code=status.HTTP_201_CREATED)
async def add_row(
    source_id: str,
    tab: str,
    body: RowIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    source = await _source(session, source_id)
    try:
        row_number, unknown = sheets.append_row(
            _spreadsheet(source), tab, body.cells)
    except SheetAdminError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    logger.info("sheet_router.add_row: %s row %s added by %s",
                tab, row_number, _who(user))
    return {"row_number": row_number, "unknown_columns": unknown}


@router.delete("/{source_id}/tabs/{tab}/rows/{row_number}")
async def remove_row(
    source_id: str,
    tab: str,
    row_number: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Delete a row, and return what was on it.

    Nothing here can undo this. The deleted contents come back in the
    response so the screen can show them and somebody can type them again;
    Google Sheets' own version history is the real recovery path.
    """
    source = await _source(session, source_id)
    try:
        removed = sheets.delete_row(_spreadsheet(source), tab, row_number)
    except SheetAdminError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    logger.warning("sheet_router.remove_row: %s row %d DELETED by %s — was %s",
                   tab, row_number, _who(user), removed)
    return {"deleted": removed, "row_number": row_number,
            "note": "This cannot be undone here. Recover it from the "
                    "spreadsheet's version history in Google Sheets."}


@router.post("/{source_id}/tabs", status_code=status.HTTP_201_CREATED)
async def add_tab(
    source_id: str,
    body: TabIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Add a tab to the spreadsheet this source points at."""
    source = await _source(session, source_id)
    try:
        created = sheets.create_tab(
            _spreadsheet(source), body.title, body.columns)
    except SheetAdminError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    logger.info("sheet_router.add_tab: %r created by %s",
                body.title, _who(user))
    return created
