"""
CSP DocMaker — CSP Google Sheets Service

Reads the live CSP data Google Sheet and syncs it to the local database.
This service handles CSP data only — authorization data is handled by
google_sheets_service.py (which remains untouched).

Reuses the same Google service account credentials.
"""

import logging
from typing import Optional, List, Dict, Tuple

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Scopes required for read-only access
# Read AND write. A correction a CSP or an RM supplies is written back
# to the sheet, which stays the source of truth — so the sheet has to
# be writable, not merely readable.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Cached service instance (separate from auth sheets service)
_csp_sheets_service = None


def _get_sheets_service():
    """Build and cache the Google Sheets API service for CSP data."""
    global _csp_sheets_service
    if _csp_sheets_service is not None:
        return _csp_sheets_service

    try:
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_sheets_credentials_file,
            scopes=SCOPES,
        )
        _csp_sheets_service = build("sheets", "v4", credentials=credentials)
        logger.info(
            "csp_gsheet_service: API client initialized for CSP data sheet"
        )
        return _csp_sheets_service
    except FileNotFoundError:
        logger.error(
            "csp_gsheet_service: credentials file not found: %s",
            settings.google_sheets_credentials_file,
        )
        raise RuntimeError(
            f"Google Sheets credentials file not found: "
            f"{settings.google_sheets_credentials_file}"
        )
    except Exception as e:
        logger.error(
            "csp_gsheet_service: failed to initialize API client: %s: %s",
            type(e).__name__, e,
        )
        raise RuntimeError(
            f"CSP Google Sheets API initialization failed: {type(e).__name__}: {e}"
        ) from e


def reset_sheets_service() -> None:
    """Throw away the cached API client so the next call builds a fresh one.

    The client is httplib2-based and holds a live socket. When the remote end
    resets the connection — which the logs show happening regularly — that
    socket is left broken inside the cached object, and the next call reuses
    it. Rebuilding after any failure keeps a poisoned connection from being
    used again.
    """
    global _csp_sheets_service
    if _csp_sheets_service is not None:
        logger.info("csp_gsheet_service: discarding the cached API client")
    _csp_sheets_service = None


def read_info_sheet() -> List[List[str]]:
    """Read the INFO tab as raw rows.

    Unlike the CSP tab this is not one table: it is four blocks with their own
    header rows, so the rows are handed back unparsed for info_directory to
    interpret. A missing or unreadable tab returns no rows — the directory is
    an enrichment, and losing it must not stop a sync.
    """
    sheet_id = settings.google_sheets_csp_sheet_id
    tab = settings.google_sheets_info_tab_name

    if not sheet_id or not tab:
        return []

    try:
        result = (
            _get_sheets_service()
            .spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=tab)
            .execute()
        )
    except HttpError as e:
        reset_sheets_service()
        logger.error(
            "csp_gsheet_service.read_info_sheet: could not read '%s' (ID: %s): "
            "status=%s, reason=%s",
            tab, sheet_id, e.resp.status, e.reason,
        )
        return []
    except Exception as e:
        reset_sheets_service()
        logger.error(
            "csp_gsheet_service.read_info_sheet: unexpected error reading '%s': %s: %s",
            tab, type(e).__name__, e,
        )
        return []

    rows = result.get("values", [])
    logger.info(
        "csp_gsheet_service.read_info_sheet: read %d row(s) from '%s'",
        len(rows), tab,
    )
    return rows


def read_csp_sheet() -> List[Dict[str, str]]:
    """Read all CSP records from the live Google Sheet.

    Returns:
        List of dicts, one per CSP row, mapping header → value.
        Returns empty list if sheet is empty or not configured.
    """
    sheet_id = settings.google_sheets_csp_sheet_id
    sheet_name = settings.google_sheets_csp_sheet_name

    if not sheet_id:
        logger.warning(
            "csp_gsheet_service.read_csp_sheet: GOOGLE_SHEETS_CSP_SHEET_ID is not configured"
        )
        return []

    try:
        service = _get_sheets_service()
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=sheet_id,
                range=sheet_name,
            )
            .execute()
        )
        values = result.get("values", [])

        if not values or len(values) < 2:
            logger.warning(
                "csp_gsheet_service.read_csp_sheet: no data in sheet '%s' (ID: %s)",
                sheet_name, sheet_id,
            )
            return []

        headers = [h.strip() for h in values[0]]
        records = []

        for row in values[1:]:
            record = {}
            for i, header in enumerate(headers):
                record[header] = row[i].strip() if i < len(row) else ""
            records.append(record)

        logger.info(
            "csp_gsheet_service.read_csp_sheet: read %d CSP record(s) from sheet '%s'",
            len(records), sheet_name,
        )
        return records

    except HttpError as e:
        reset_sheets_service()
        logger.error(
            "csp_gsheet_service.read_csp_sheet: API error reading sheet '%s' (ID: %s): "
            "status=%s, reason=%s",
            sheet_name, sheet_id, e.resp.status, e.reason,
        )
        raise RuntimeError(
            f"Google Sheets API error reading CSP sheet '{sheet_name}': "
            f"HTTP {e.resp.status} — {e.reason}"
        ) from e
    except Exception as e:
        reset_sheets_service()
        logger.error(
            "csp_gsheet_service.read_csp_sheet: unexpected error: %s: %s",
            type(e).__name__, e,
        )
        raise RuntimeError(
            f"Failed to read CSP Google Sheet: {type(e).__name__}: {e}"
        ) from e


# Default column name mapping — maps Google Sheet header → CSP model field
# Supports case-insensitive matching
DEFAULT_COLUMN_MAP = {
    "csp id": "csp_id",
    "csp code": "csp_code",
    "csp name": "name",
    "name": "name",
    "email": "email",
    "email id": "email_id",
    "mobile": "mobile",
    "mobile number": "mobile",
    "phone": "mobile",
    "address": "address",
    "branch name": "branch_name",
    "branch code": "branch_code",
    "module name": "module_name",
    "rbo name": "rbo_name",
    "onboarding date": "onboarded_date",
    "onboarded date": "onboarded_date",
    "onboarding month": "onboarding_month",
    "onboarding year": "onboarding_year",
    "status": "status",
    "photo": "photo_url",
    "photo url": "photo_url",
}


def map_row_to_csp_fields(row: Dict[str, str]) -> Dict[str, str]:
    """Map a Google Sheet row (header → value) to CSP model field names.

    Uses case-insensitive matching against DEFAULT_COLUMN_MAP.

    Args:
        row: Dict mapping sheet column headers to values.

    Returns:
        Dict mapping CSP model field names to values.
    """
    mapped = {}
    for header, value in row.items():
        header_lower = header.strip().lower()
        field_name = DEFAULT_COLUMN_MAP.get(header_lower)
        if field_name and value.strip():
            mapped[field_name] = value.strip()
    return mapped
