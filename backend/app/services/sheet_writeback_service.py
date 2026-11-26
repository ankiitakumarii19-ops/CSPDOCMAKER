"""
CSP DocMaker — writing a correction back to the CSP sheet

The sheet is the source of truth, and the sync reads it every minute. So a
correction that lives only in the database is undone by the next pass: the
sheet still says what it always said, and the sync faithfully restores it.
Anything a CSP or an RM supplies therefore has to reach the sheet.

What this will not do, and why:

  * It will not write a blank over a value. An empty box on a form means
    "nothing to add", never "delete what you have".
  * It will not write to a row it cannot identify beyond doubt. Two rows
    carrying the same CSP Code, or none, stops the write — guessing would
    put one CSP's details onto another's row.
  * It will not invent a column. A field with no header in the sheet is
    reported back, not silently dropped, because the caller has just told
    somebody their answer was saved.

Columns are located by reading the live header row, so moving a column in
the sheet does not corrupt anything.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from app.config import get_settings
from app.services import csp_mapping
from app import telemetry

logger = logging.getLogger(__name__)


class SheetWriteError(RuntimeError):
    """The correction could not be written to the sheet."""


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    if index < 0:
        raise ValueError("Column index cannot be negative.")
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def find_columns(header: List[str]) -> Dict[str, int]:
    """Canonical field -> its column index in this sheet, as it is today."""
    columns: Dict[str, int] = {}
    for index, title in enumerate(header):
        field = csp_mapping.field_for_header(title)   # own columns (No. 211)
        if field and field not in columns:
            columns[field] = index
    if csp_mapping.IDENTITY_FIELD not in columns:
        # No. 263: a workspace's own name for the code column (Setup ->
        # Columns) that is not in the sheet must not lose the row when the
        # standard "CSP Code" heading is right there. Said, not silent.
        eko = _norm(csp_mapping.FIELD_TO_SHEET_COLUMN[csp_mapping.IDENTITY_FIELD])
        for index, title in enumerate(header):
            if _norm(title) == eko:
                columns[csp_mapping.IDENTITY_FIELD] = index
                logger.warning(
                    "sheet_writeback_service.find_columns: the code column's "
                    "own name %r (Setup -> Columns) is not in the sheet; "
                    "using the %r column", csp_mapping.header_for(
                        csp_mapping.IDENTITY_FIELD), title)
                break
    return columns


# How far down the tab the heading row is looked for (No. 263).
HEADER_SEARCH_ROWS = 5


def locate_header(rows: List[List[str]], tab: str) -> Tuple[int, Dict[str, int]]:
    """(0-based index of the heading row, its columns).

    The heading is row 1. A row put above it (a title, a note) used to stop
    every write with "no CSP Code column"; the first few rows are now looked
    at. When none has it, the error says what row 1 actually reads, so the
    cause can be seen from the Admin page without a server login.
    """
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        columns = find_columns(row)
        if csp_mapping.IDENTITY_FIELD in columns:
            if index:
                logger.warning(
                    "sheet_writeback_service.locate_header: the headings of "
                    "%s are on row %d, not row 1", tab, index + 1)
            return index, columns

    first = [str(h).strip() for h in (rows[0] if rows else []) if str(h).strip()]
    shown = ", ".join(first[:6]) + (" ..." if len(first) > 6 else "")
    wanted = csp_mapping.header_for(csp_mapping.IDENTITY_FIELD) or "CSP Code"
    raise SheetWriteError(
        f"The {tab} tab has no {wanted} column, so a row cannot be found. "
        f"Row 1 reads: {shown or '(empty)'}.")


def find_row(rows: List[List[str]], code_column: int, csp_code: str,
             header_row: int = 0) -> int:
    """The 1-based sheet row for this CSP Code.

    `header_row` is the 0-based index of the heading row; data starts below.
    Raises when the code appears twice or not at all: both mean the right
    row is not known, and writing to the wrong one is worse than failing.
    """
    wanted = _norm(csp_code)
    if not wanted:
        raise SheetWriteError("Cannot write back without a CSP Code.")

    matches = [
        number for number, row in enumerate(rows[header_row + 1:],
                                            start=header_row + 2)
        if code_column < len(row) and _norm(row[code_column]) == wanted
    ]
    if not matches:
        raise SheetWriteError(
            f"CSP Code {csp_code} is not in the sheet, so there is no row to "
            f"update.")
    if len(matches) > 1:
        raise SheetWriteError(
            f"CSP Code {csp_code} appears on rows {matches}. The sheet has to "
            f"say which one is right before anything is written to it.")
    return matches[0]


@telemetry.traced("write_back_to_sheet", "sheet_writeback_service")
def write_values(
    csp_code: str,
    values: Dict[str, str],
    tab: Optional[str] = None,
    value_input: str = "RAW",
) -> Tuple[Dict[str, str], List[str]]:
    """Write these field values onto this CSP's row.

    value_input is "RAW" (text exactly as given — a CSP's answers) or
    "USER_ENTERED" (read as if typed — needed for an =IMAGE() formula).

    Returns (written, skipped): what reached the sheet, and the fields that
    have no column there. A caller that has just told someone their answer
    was saved needs to know which ones were not.
    """
    from app.services import csp_gsheet_service as sheets

    settings = get_settings()
    # KOData or SUBKOData, by the length of the code (No. 57).
    tab = tab or settings.csp_tab_for(csp_code)

    # A blank never overwrites a value.
    wanted = {f: str(v).strip() for f, v in (values or {}).items()
              if str(v or "").strip()}
    if not wanted:
        return {}, []

    service = sheets._get_sheets_service()
    try:
        rows = service.spreadsheets().values().get(
            spreadsheetId=settings.google_sheets_csp_sheet_id,
            range=tab,
        ).execute().get("values", [])
    except Exception as e:
        sheets.reset_sheets_service()
        raise SheetWriteError(
            f"Could not read {tab} to locate the row: {type(e).__name__}: {e}"
        ) from e

    if not rows:
        raise SheetWriteError(f"The {tab} tab is empty.")

    try:
        header_row, columns = locate_header(rows, tab)
    except SheetWriteError as e:
        logger.error("sheet_writeback_service.write_values: CSP %s: %s",
                     csp_code, e)
        raise

    row_number = find_row(rows, columns[csp_mapping.IDENTITY_FIELD], csp_code,
                          header_row)

    data, written, skipped = [], {}, []
    for field, value in wanted.items():
        index = columns.get(field)
        if index is None:
            skipped.append(field)
            continue
        cell = f"{tab}!{column_letter(index)}{row_number}"
        data.append({"range": cell, "values": [[value]]})
        written[field] = value

    if data:
        try:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=settings.google_sheets_csp_sheet_id,
                body={"valueInputOption": value_input, "data": data},
            ).execute()
        except Exception as e:
            sheets.reset_sheets_service()
            raise SheetWriteError(
                f"Could not write to {tab}: {type(e).__name__}: {e}") from e

    logger.info(
        "sheet_writeback_service.write_values: CSP %s row %d — wrote %s%s",
        csp_code, row_number, sorted(written),
        f", no column for {sorted(skipped)}" if skipped else "",
    )
    return written, skipped
