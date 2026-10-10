"""
CSP DocMaker — Google Sheets Authorization Service

Reads the Authorization Google Sheet (RMs tab and Admins tab) to check
whether a user is authorized for a given role.

This service is ONLY for the authorization sheet. CSP data comes from
a separate Google Sheet (handled by csp_gsheet_service).
"""

import logging
from typing import Optional, List, Dict

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

# Cached service instance
_sheets_service = None


def _get_sheets_service():
    """Build and cache the Google Sheets API service."""
    global _sheets_service
    if _sheets_service is not None:
        return _sheets_service

    try:
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_sheets_credentials_file,
            scopes=SCOPES,
        )
        _sheets_service = build("sheets", "v4", credentials=credentials)
        logger.info(
            "google_sheets_service: API client initialized with credentials from %s",
            settings.google_sheets_credentials_file,
        )
        return _sheets_service
    except FileNotFoundError:
        logger.error(
            "google_sheets_service: credentials file not found: %s",
            settings.google_sheets_credentials_file,
        )
        raise RuntimeError(
            f"Google Sheets credentials file not found: "
            f"{settings.google_sheets_credentials_file}. "
            f"Ensure the service account JSON file is in the correct location."
        )
    except Exception as e:
        logger.error(
            "google_sheets_service: failed to initialize API client: %s: %s",
            type(e).__name__, e,
        )
        raise RuntimeError(
            f"Google Sheets API initialization failed: {type(e).__name__}: {e}"
        ) from e


def reset_sheets_service() -> None:
    """Discard the cached API client after a failure.

    Same reasoning as csp_gsheet_service: the httplib2 client holds a socket
    that a connection reset leaves broken, and reusing it is worse than
    paying to rebuild.
    """
    global _sheets_service
    if _sheets_service is not None:
        logger.info("google_sheets_service: discarding the cached API client")
    _sheets_service = None


def _read_sheet_tab(sheet_name: str) -> List[List[str]]:
    """Read all rows from a specific tab in the authorization Google Sheet.

    Args:
        sheet_name: Tab name (e.g. 'RMs' or 'Admins').

    Returns:
        List of rows, where each row is a list of cell values.
        First row is the header.
    """
    try:
        service = _get_sheets_service()
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=settings.google_sheets_id,
                range=f"{sheet_name}",
            )
            .execute()
        )
        values = result.get("values", [])
        if not values:
            logger.warning(
                "google_sheets_service._read_sheet_tab: no data in tab '%s' of sheet %s",
                sheet_name, settings.google_sheets_id,
            )
        return values
    except HttpError as e:
        reset_sheets_service()
        logger.error(
            "google_sheets_service._read_sheet_tab: API error reading tab '%s': "
            "status=%s, reason=%s",
            sheet_name, e.resp.status, e.reason,
        )
        raise RuntimeError(
            f"Google Sheets API error reading tab '{sheet_name}': "
            f"HTTP {e.resp.status} — {e.reason}"
        ) from e
    except Exception as e:
        reset_sheets_service()
        logger.error(
            "google_sheets_service._read_sheet_tab: unexpected error reading tab '%s': %s: %s",
            sheet_name, type(e).__name__, e,
        )
        raise RuntimeError(
            f"Failed to read Google Sheet tab '{sheet_name}': {type(e).__name__}: {e}"
        ) from e


# A row authorizes a user only when its Status cell says exactly this.
# Any other value — including blank — denies access, so removing or
# de-activating someone in the sheet takes effect immediately.
ACTIVE_STATUS = "active"


def is_active(row: Dict[str, str]) -> bool:
    """True when the sheet row's Status column marks the user as active."""
    for key, value in row.items():
        if key.strip().lower() == "status":
            return value.strip().lower() == ACTIVE_STATUS
    # No Status column at all — treat the sheet as not carrying the signal
    # rather than silently granting access.
    return False


def get_field(row: Dict[str, str], *candidates: str) -> str:
    """Read a row value by header name, ignoring case, spaces and underscores.

    The authorization sheet uses headers like 'Name ', 'Email_id' and
    'Contact_no', so exact-key lookups are unreliable.
    """
    def norm(text: str) -> str:
        return text.strip().lower().replace("_", "").replace(" ", "")

    normalized = {norm(k): v.strip() for k, v in row.items()}
    for candidate in candidates:
        if norm(candidate) in normalized:
            return normalized[norm(candidate)]
    return ""


def _find_email_in_rows(rows: List[List[str]], email: str) -> Optional[Dict[str, str]]:
    """Search for an email in the sheet rows.

    Assumes row 0 is the header row. Searches all rows for a matching email
    in any column whose header contains 'email' (case-insensitive).

    Returns:
        Dict mapping header → value for the matched row, or None.
    """
    if not rows or len(rows) < 2:
        return None

    headers = [h.strip().lower() for h in rows[0]]

    # Find email column index
    email_col_idx = None
    for i, h in enumerate(headers):
        if "email" in h:
            email_col_idx = i
            break

    if email_col_idx is None:
        logger.warning(
            "google_sheets_service._find_email_in_rows: no 'email' column found in headers: %s",
            headers,
        )
        return None

    email_lower = email.strip().lower()
    for row in rows[1:]:
        if len(row) > email_col_idx:
            if row[email_col_idx].strip().lower() == email_lower:
                # Build dict from headers
                result = {}
                for i, h in enumerate(rows[0]):
                    result[h.strip()] = row[i].strip() if i < len(row) else ""
                return result

    return None


def check_authorization(email: str, requested_role: str) -> tuple[bool, Optional[Dict[str, str]]]:
    """Check if a user email is authorized for the requested role.

    Reads the appropriate tab (RMs or Admins) from the authorization
    Google Sheet and checks if the email exists.

    Args:
        email: The user's email address.
        requested_role: 'rm' or 'admin'.

    Returns:
        Tuple of (authorized, user_data).
        authorized is True if the email is found in the correct tab.
        user_data is the row data dict if found, None otherwise.
    """
    if requested_role == "admin":
        sheet_name = settings.google_sheets_admin_sheet_name
    elif requested_role == "rm":
        sheet_name = settings.google_sheets_rm_sheet_name
    else:
        logger.warning(
            "google_sheets_service.check_authorization: invalid role '%s' for %s",
            requested_role, email,
        )
        return False, None

    try:
        rows = _read_sheet_tab(sheet_name)
        user_data = _find_email_in_rows(rows, email)

        if user_data:
            if not is_active(user_data):
                logger.info(
                    "google_sheets_service.check_authorization: %s found in %s tab "
                    "but Status is not '%s' — access denied",
                    email, sheet_name, ACTIVE_STATUS,
                )
                return False, None
            logger.info(
                "google_sheets_service.check_authorization: %s authorized as %s",
                email, requested_role,
            )
            return True, user_data
        else:
            logger.info(
                "google_sheets_service.check_authorization: %s NOT found in %s tab",
                email, sheet_name,
            )
            return False, None

    except RuntimeError:
        # Re-raise — already logged with details
        raise
    except Exception as e:
        logger.error(
            "google_sheets_service.check_authorization: unexpected error for %s: %s: %s",
            email, type(e).__name__, e,
        )
        raise RuntimeError(
            f"Authorization check failed for {email}: {type(e).__name__}: {e}"
        ) from e


def get_all_authorized_users(role: str) -> List[Dict[str, str]]:
    """Get all authorized users for a given role.

    Args:
        role: 'rm' or 'admin'.

    Returns:
        List of dicts, one per authorized user, mapping header → value.
    """
    if role == "admin":
        sheet_name = settings.google_sheets_admin_sheet_name
    elif role == "rm":
        sheet_name = settings.google_sheets_rm_sheet_name
    else:
        return []

    rows = _read_sheet_tab(sheet_name)
    if not rows or len(rows) < 2:
        return []

    headers = rows[0]
    users = []
    for row in rows[1:]:
        user = {}
        for i, h in enumerate(headers):
            user[h.strip()] = row[i].strip() if i < len(row) else ""
        users.append(user)

    return users
