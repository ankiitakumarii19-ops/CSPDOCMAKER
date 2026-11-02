"""
CSP DocMaker — editing one CSP from the portal (No. 175)

The Database page used to be read-only ("changes are made in the sheet").
Now a CSP's whole sheet row (KOData or SUBKOData, by code) opens as a form;
a save writes the changed cells to the Google Sheet — the source of truth
(D3) — and to the record at once, so portal and sheet match without waiting
for the next sync.

Rules:
  * RMs edit their own CSPs and unowned ones (csp_access.can_access); Admins
    and Super Admins any. The same rule now holds on the Sheets tab (owner's
    choice, 2 Nov 2026).
  * The CSP Code cannot be changed here (it is how the row is found). The RM
    Name can — the CSP then belongs to the RM named (owner's choice).
  * Checked first: a CSP Name and mobile cannot be blank; a phone column
    holds a usable Indian mobile (two in one cell allowed, No. 144); an
    email column holds an email address.
  * A save is refused when the sheet changed since the form was opened
    (another person, or the sheet itself) — nothing is overwritten unseen.
  * Every changed field is logged (audit "csp_edit": who, column, old, new,
    when, from where) and shown in the CSP's record.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select

from app.config import get_settings
from app.models.audit_log import AuditLog
from app.services import csp_mapping

logger = logging.getLogger(__name__)

ACTION = "csp_edit"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
REQUIRED = ("name", "mobile")
LOCKED = (csp_mapping.IDENTITY_FIELD,)


class EditError(ValueError):
    """Refused, with a message fit to show (and per-column problems)."""

    def __init__(self, message: str, problems: Optional[Dict[str, str]] = None,
                 status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.problems = problems or {}
        self.status_code = status_code


def field_of(column: str) -> Optional[str]:
    from app.services.sheet_writeback_service import _norm

    return csp_mapping.SHEET_COLUMN_TO_FIELD.get(_norm(column)) or next(
        (f for c, f in csp_mapping.SHEET_COLUMN_TO_FIELD.items()
         if _norm(c) == _norm(column)), None)


def kind_of(column: str, field: Optional[str]) -> str:
    """phone / email / text, for the check and for the form's input box."""
    words = f"{column} {field or ''}".lower()
    if "email" in words or "e-mail" in words or "mail id" in words:
        return "email"
    if any(w in words for w in ("mobile", "contact", "phone", "whatsapp")):
        return "phone"
    return "text"


def check(column: str, field: Optional[str], value: str) -> Optional[str]:
    """What is wrong with this value for this column, or None."""
    from app.services.alert_composer import normalize_mobile

    value = (value or "").strip()
    if field in REQUIRED and not value:
        return "Cannot be blank."
    if not value:
        return None
    kind = kind_of(column, field)
    if kind == "email" and not _EMAIL.match(value):
        return "Not an email address."
    if kind == "phone":
        parts = [p for p in re.split(r"[/,;|]+", value) if p.strip()]
        if not parts or not all(normalize_mobile(p) for p in parts):
            return "Not a 10-digit Indian mobile number."
    return None


def _rows(tab: str) -> List[List[str]]:
    from app.services import csp_gsheet_service as sheets
    from app.services.sheet_writeback_service import SheetWriteError

    try:
        return sheets._get_sheets_service().spreadsheets().values().get(
            spreadsheetId=get_settings().google_sheets_csp_sheet_id,
            range=tab).execute().get("values", [])
    except Exception as e:
        sheets.reset_sheets_service()
        raise SheetWriteError(f"Could not read {tab}: {type(e).__name__}: {e}") from e


def load(code: str) -> dict:
    """The CSP's row as the form shows it: every column, its value, kind."""
    from app.services.sheet_writeback_service import (SheetWriteError,
                                                      find_columns, find_row)

    settings = get_settings()
    if not settings.google_sheets_csp_sheet_id:
        raise EditError("The CSP sheet is not set up on this copy of the app.",
                        status_code=503)
    tab = settings.csp_tab_for(code)
    rows = _rows(tab)
    if not rows:
        raise EditError(f"The {tab} tab is empty.", status_code=409)
    header = rows[0]
    columns = find_columns(header)
    if csp_mapping.IDENTITY_FIELD not in columns:
        raise EditError(f"The {tab} tab has no CSP Code column.", status_code=409)
    try:
        number = find_row(rows, columns[csp_mapping.IDENTITY_FIELD], code)
    except SheetWriteError as e:
        raise EditError(str(e), status_code=409)
    row = rows[number - 1]
    out = []
    for i, title in enumerate(header):
        if not str(title).strip():
            continue
        field = field_of(title)
        out.append({"column": title, "field": field,
                    "value": row[i] if i < len(row) else "",
                    "kind": kind_of(title, field),
                    "required": field in REQUIRED,
                    "locked": field in LOCKED})
    return {"tab": tab, "row_number": number, "columns": out}


def save(session, code: str, changes: Dict[str, str], seen: Dict[str, str],
         who: str, via: str = "database") -> dict:
    """Write the changed columns. `seen` = their values when the form opened.
    The caller has checked the person may edit this CSP. Commits nothing."""
    from app.services import alert_service, field_quality
    from app.services import sheet_admin_service as admin

    if not changes:
        raise EditError("Nothing was changed.")
    current = load(code)
    by_column = {c["column"]: c for c in current["columns"]}

    problems = {}
    for column, value in changes.items():
        col = by_column.get(column)
        if col is None:
            problems[column] = "No such column in the sheet."
        elif col["locked"]:
            problems[column] = "The CSP Code cannot be changed here."
        elif (col["value"] or "").strip() != (seen.get(column) or "").strip():
            problems[column] = (f"Changed in the sheet since you opened it "
                                f"(now {col['value']!r}). Reload and try again.")
        else:
            why = check(column, col["field"], value)
            if why:
                problems[column] = why
    if problems:
        conflict = any("since you opened" in p for p in problems.values())
        raise EditError("Not saved: please fix the marked fields.", problems,
                        status_code=409 if conflict else 400)

    real = {c: str(v).strip() for c, v in changes.items()
            if str(v).strip() != (by_column[c]["value"] or "").strip()}
    if not real:
        raise EditError("Nothing was changed.")
    written, unknown = admin.update_row(get_settings().google_sheets_csp_sheet_id,
                                        current["tab"], current["row_number"], real)
    if unknown:
        logger.warning("csp_editor: %s — columns not in the sheet: %s", code, unknown)

    record_changes = log_changes(session, code, {
        c: (by_column[c]["value"], v) for c, v in written.items()}, who, via)
    _apply_to_record(session, code, written)
    try:
        with session.begin_nested():
            field_quality.record_check(session, code, record_changes,
                                       "sheet_editor", who, False)
    except Exception as e:
        logger.error("csp_editor: %s saved, but its quality note was not: "
                     "%s: %s", code, type(e).__name__, e, exc_info=True)
    try:
        with session.begin_nested():
            from app.models.rm_alert import RMAlert
            alert_service.recheck(session, list(session.execute(
                select(RMAlert).where(RMAlert.csp_id == code)).scalars()))
    except Exception as e:
        logger.error("csp_editor: %s saved, but Action Required was not "
                     "re-checked: %s: %s", code, type(e).__name__, e, exc_info=True)
    logger.info("csp_editor: %s changed %s by %s (%s)", code,
                sorted(written), who, via)
    return {"written": written, "unknown": unknown}


def log_changes(session, code: str, changes: Dict[str, Tuple[str, str]],
                who: str, via: str) -> Dict[str, str]:
    """One audit row per changed column. Returns the changes by record field
    (for the quality notes)."""
    by_field = {}
    for column, (old, new) in changes.items():
        if (old or "").strip() == (new or "").strip():
            continue
        field = field_of(column)
        if field:
            by_field[field] = new
        session.add(AuditLog(
            action=ACTION, resource_type="csp", resource_id=code, csp_id=code,
            result="success",
            metadata_json={"by": who, "via": via, "column": column,
                           "field": field, "old": (old or "")[:1000],
                           "new": (new or "")[:1000]}))
    return by_field


def _apply_to_record(session, code: str, written: Dict[str, str]) -> None:
    """The record matches the sheet now, not at the next sync."""
    from app.models.csp_record import CSPRecord

    record = session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == code)).scalars().first()
    if record is None:
        return
    for field, value in csp_mapping.map_sheet_row(written).items():
        attr = csp_mapping.FIELD_TO_CSP_ATTR.get(field, field)
        if field != csp_mapping.IDENTITY_FIELD and hasattr(record, attr):
            setattr(record, attr, value)


def history(session, code: str, limit: int = 200) -> List[dict]:
    rows = session.execute(
        select(AuditLog).where(AuditLog.action == ACTION, AuditLog.csp_id == code)
        .order_by(AuditLog.created_at.desc()).limit(limit)).scalars().all()
    return [{"at": r.created_at.isoformat() if r.created_at else None,
             **{k: (r.metadata_json or {}).get(k)
                for k in ("by", "via", "column", "field", "old", "new")}}
            for r in rows]
