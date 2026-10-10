"""
CSP DocMaker — looking at, and changing, the sheets a workspace reads

A Super Admin can see every sheet this workspace is configured to read,
open any tab in it, and edit, add or remove rows. What they change is
written to the spreadsheet itself — there is no copy to drift out of date,
and anyone looking at the Google Sheet sees the same thing a moment later.

Three decisions shape this module.

**Tabs are read live, never remembered.** A tab added or removed in Google
Sheets appears or disappears here on the next look, because the list comes
from the spreadsheet every time rather than from a table that would have
to be kept in step.

**A row is addressed by its sheet row number.** Not by an index into a
filtered list, which would move under a concurrent edit and write to the
wrong person's row. The number shown is the number in the spreadsheet.

**Deleting is real.** There is no undo here; recovery means Google Sheets'
own version history. So a delete reads the row first and returns what it
removed, which gives the caller something to show, to log, and to put back
by hand if it was a mistake.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from app.config import get_settings

logger = logging.getLogger(__name__)

# A spreadsheet this size is a different product. Reading it whole into a
# browser would help nobody, so the screen says so instead of hanging.
MAX_ROWS = 2000


class SheetAdminError(RuntimeError):
    """Something about the sheet, the tab or the row is wrong."""


def _service():
    from app.services import csp_gsheet_service as sheets

    return sheets._get_sheets_service()


def _reset():
    from app.services import csp_gsheet_service as sheets

    sheets.reset_sheets_service()


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _quote_tab(tab: str) -> str:
    """A tab whose name has a space needs quoting in an A1 range."""
    if re.fullmatch(r"[A-Za-z0-9_]+", tab or ""):
        return tab
    return "'" + (tab or "").replace("'", "''") + "'"


# ---- what is there ------------------------------------------------------

def describe(spreadsheet_id: str) -> dict:
    """The spreadsheet's name and its tabs, in ONE call to Google.

    Asking for the title and the tabs separately meant two round trips per
    spreadsheet, and the screen was making six of them to show three
    sources — most of a four-second wait spent asking Google the same
    question twice. The response already carries both.

    Read fresh each time rather than cached: a tab created or deleted in
    Google Sheets has to show up here, and a cache would be a reason it
    did not.
    """
    try:
        meta = _service().spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="properties.title,sheets.properties",
        ).execute()
    except Exception as e:
        _reset()
        raise SheetAdminError(
            f"Could not open that spreadsheet: {type(e).__name__}: {e}"
        ) from e

    tabs = []
    for sheet in meta.get("sheets", []):
        properties = sheet.get("properties", {})
        grid = properties.get("gridProperties", {})
        tabs.append({
            "tab_id": properties.get("sheetId"),
            "title": properties.get("title", ""),
            "rows": grid.get("rowCount"),
            "columns": grid.get("columnCount"),
        })
    return {
        "title": meta.get("properties", {}).get("title", ""),
        "tabs": tabs,
    }


def list_tabs(spreadsheet_id: str) -> List[dict]:
    """Every tab in the spreadsheet, as it stands right now."""
    return describe(spreadsheet_id)["tabs"]


def spreadsheet_title(spreadsheet_id: str) -> str:
    try:
        return describe(spreadsheet_id)["title"]
    except SheetAdminError:
        return ""


def _tab_id(spreadsheet_id: str, tab: str) -> int:
    for found in list_tabs(spreadsheet_id):
        if found["title"] == tab:
            return found["tab_id"]
    raise SheetAdminError(
        f"That spreadsheet has no tab called {tab!r}. It may have been "
        f"renamed or deleted."
    )


# ---- reading ------------------------------------------------------------

def read_tab(spreadsheet_id: str, tab: str) -> dict:
    """The tab's header and rows, each row carrying its sheet row number."""
    try:
        values = _service().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=_quote_tab(tab),
        ).execute().get("values", [])
    except Exception as e:
        _reset()
        raise SheetAdminError(
            f"Could not read {tab!r}: {type(e).__name__}: {e}"
        ) from e

    if not values:
        return {"tab": tab, "columns": [], "rows": [], "truncated": False}

    header = [str(h).strip() for h in values[0]]
    body = values[1:]
    truncated = len(body) > MAX_ROWS
    body = body[:MAX_ROWS]

    rows = []
    for offset, raw in enumerate(body):
        # Row 1 is the header, so the first data row is sheet row 2.
        cells = {header[i]: (raw[i] if i < len(raw) else "")
                 for i in range(len(header)) if header[i]}
        rows.append({"row_number": offset + 2, "cells": cells})

    return {"tab": tab, "columns": [h for h in header if h], "rows": rows,
            "truncated": truncated}


# ---- changing -----------------------------------------------------------

def _header(spreadsheet_id: str, tab: str) -> List[str]:
    try:
        values = _service().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_tab(tab)}!1:1",
        ).execute().get("values", [[]])
    except Exception as e:
        _reset()
        raise SheetAdminError(
            f"Could not read the header of {tab!r}: {type(e).__name__}: {e}"
        ) from e
    return [str(h).strip() for h in (values[0] if values else [])]


def update_row(spreadsheet_id: str, tab: str, row_number: int,
               cells: Dict[str, str]) -> Tuple[Dict[str, str], List[str]]:
    """Write these columns onto this row. Returns (written, unknown columns).

    A column the tab does not have is reported rather than created: adding
    a column changes what every reader of this sheet sees, and that is a
    deliberate act, not a side effect of a typo in a cell name.
    """
    if row_number < 2:
        raise SheetAdminError(
            "Row 1 is the header. Editing it would rename the columns every "
            "other part of the system matches on.")

    header = _header(spreadsheet_id, tab)
    if not header:
        raise SheetAdminError(f"{tab!r} has no header row.")

    data, written, unknown = [], {}, []
    for name, value in (cells or {}).items():
        if name not in header:
            unknown.append(name)
            continue
        letter = column_letter(header.index(name))
        data.append({
            "range": f"{_quote_tab(tab)}!{letter}{row_number}",
            "values": [[str(value)]],
        })
        written[name] = str(value)

    if data:
        try:
            _service().spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": data},
            ).execute()
        except Exception as e:
            _reset()
            raise SheetAdminError(
                f"Could not write to {tab!r} row {row_number}: "
                f"{type(e).__name__}: {e}"
            ) from e
        logger.info("sheet_admin_service: %s row %d updated (%s)",
                    tab, row_number, ", ".join(sorted(written)))

    return written, unknown


def append_row(spreadsheet_id: str, tab: str,
               cells: Dict[str, str]) -> Tuple[int, List[str]]:
    """Add a row at the end. Returns (its row number, unknown columns)."""
    header = _header(spreadsheet_id, tab)
    if not header:
        raise SheetAdminError(f"{tab!r} has no header row.")

    unknown = [name for name in (cells or {}) if name not in header]
    row = [str((cells or {}).get(name, "")) for name in header]

    try:
        result = _service().spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=_quote_tab(tab),
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
    except Exception as e:
        _reset()
        raise SheetAdminError(
            f"Could not add a row to {tab!r}: {type(e).__name__}: {e}"
        ) from e

    # The API reports where it landed, e.g. "CSPData!A10:AA10".
    updated = result.get("updates", {}).get("updatedRange", "")
    match = re.search(r"!\D+(\d+)", updated)
    row_number = int(match.group(1)) if match else -1
    logger.info("sheet_admin_service: %s row %s added", tab, row_number)
    return row_number, unknown


def delete_row(spreadsheet_id: str, tab: str, row_number: int) -> Dict[str, str]:
    """Remove a row, and return what was on it.

    Nothing here can put it back. Returning the contents gives the caller
    something to show the person who did it and something to type back in
    if it was a mistake; Google Sheets' version history is the real undo.
    """
    if row_number < 2:
        raise SheetAdminError(
            "Row 1 is the header and cannot be deleted.")

    existing = read_tab(spreadsheet_id, tab)
    doomed = next((r for r in existing["rows"]
                   if r["row_number"] == row_number), None)
    if doomed is None:
        raise SheetAdminError(
            f"{tab!r} has no row {row_number}. It may already be gone.")

    tab_id = _tab_id(spreadsheet_id, tab)
    try:
        _service().spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteDimension": {"range": {
                "sheetId": tab_id,
                "dimension": "ROWS",
                # The API counts from 0; a sheet row number counts from 1.
                "startIndex": row_number - 1,
                "endIndex": row_number,
            }}}]},
        ).execute()
    except Exception as e:
        _reset()
        raise SheetAdminError(
            f"Could not delete {tab!r} row {row_number}: "
            f"{type(e).__name__}: {e}"
        ) from e

    logger.warning("sheet_admin_service: %s row %d DELETED — contents were %s",
                   tab, row_number, doomed["cells"])
    return doomed["cells"]


def create_tab(spreadsheet_id: str, title: str,
               columns: Optional[List[str]] = None) -> dict:
    """Add a tab, optionally with a header row already written."""
    title = (title or "").strip()
    if not title:
        raise SheetAdminError("A tab needs a name.")
    if any(t["title"] == title for t in list_tabs(spreadsheet_id)):
        raise SheetAdminError(f"That spreadsheet already has a tab called "
                              f"{title!r}.")
    try:
        result = _service().spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()
    except Exception as e:
        _reset()
        raise SheetAdminError(
            f"Could not add the tab {title!r}: {type(e).__name__}: {e}"
        ) from e

    properties = (result.get("replies", [{}])[0]
                  .get("addSheet", {}).get("properties", {}))
    if columns:
        _service().spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{_quote_tab(title)}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [list(columns)]},
        ).execute()

    logger.info("sheet_admin_service: tab %r created", title)
    return {"tab_id": properties.get("sheetId"), "title": title}
