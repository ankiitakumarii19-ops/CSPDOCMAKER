"""
CSP DocMaker — all settings as one Excel sheet (PROJECT-REGISTER No. 215,
Stage 8: TK-068, ZU-07)

Download: one row per setting — its key, group, name, this workspace's
value, the standard (Eko's) value, what is allowed and what it is. Change
the "Your value" column in Excel, upload it, and the app shows every change
first (and any value it refuses, with why); "Apply" saves them through the
same checks and history as the Settings screen (via "sheet").

The same file is how a workspace's settings are COPIED to another: download
in one, upload in the other. Connections, passwords and people are never in
it.
"""

import io
from typing import Any, Dict, List

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.services import settings_catalog as catalog
from app.services.settings_catalog import SettingError

HEADERS = ["Key", "Group", "Setting", "Your value", "Standard (Eko's)",
           "Allowed", "What it is"]
VALUE_COL = 4


def _cell(s, value) -> Any:
    if s.kind == catalog.BOOL:
        return "On" if value else "Off"
    return value


def _allowed(s) -> str:
    if s.kind == catalog.BOOL:
        return "On / Off"
    if s.kind == catalog.INT:
        return f"{s.min} - {s.max}" + (f" {s.unit}" if s.unit else "")
    if s.kind in (catalog.CHOICE, catalog.LIST):
        many = " (comma separated)" if s.kind == catalog.LIST else ""
        return (", ".join(s.choices) if s.choices else "document codes") + many
    return f"text, {s.min or 0}-{s.max or 1000} characters"


def build(view: dict) -> bytes:
    """view = workspace_settings.describe(...)."""
    groups = {g["key"]: g["title"] for g in view["groups"]}
    wb = Workbook()
    ws = wb.active
    ws.title = "Settings"
    ws.append(HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
    for item in view["settings"]:
        s = catalog.BY_KEY[item["key"]]
        ws.append([s.key, groups.get(s.group, s.group), s.label,
                   _cell(s, item["value"]), _cell(s, item["standard"]),
                   _allowed(s), s.help])
    for col, width in zip("ABCDEFG", (28, 22, 36, 22, 22, 26, 70)):
        ws.column_dimensions[col].width = width
    yellow = PatternFill("solid", fgColor="FFF2CC")
    for row in ws.iter_rows(min_row=2):
        row[VALUE_COL - 1].fill = yellow
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "D2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def read(data: bytes) -> Dict[str, Any]:
    """{key: value as typed} for every known key in the uploaded sheet."""
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as e:
        raise SettingError(f"That is not an Excel file the app can read "
                           f"({type(e).__name__}).")
    ws = wb["Settings"] if "Settings" in wb.sheetnames else wb.active
    rows = ws.iter_rows(values_only=True)
    header = [str(h or "").strip() for h in next(rows, [])]
    if "Key" not in header or "Your value" not in header:
        raise SettingError("The sheet needs its “Key” and “Your value” "
                           "columns — download a fresh one.")
    k, v = header.index("Key"), header.index("Your value")
    out = {}
    for row in rows:
        if not row or row[k] is None:
            continue
        key = str(row[k]).strip()
        if key in catalog.BY_KEY:
            out[key] = row[v] if row[v] is not None else ""
    return out


def preview(current: Dict[str, Any], uploaded: Dict[str, Any]) -> List[dict]:
    """Each change the sheet asks for, checked; nothing saved."""
    changes = []
    in_force = dict(current)
    for key, raw in uploaded.items():
        s = catalog.BY_KEY[key]
        item = {"key": key, "label": s.label,
                "now": catalog.show(s, current.get(key))}
        try:
            value = catalog.parse(s, raw)
        except SettingError as e:
            changes.append({**item, "new": str(raw), "problem": str(e)})
            continue
        if value == current.get(key):
            continue
        in_force[key] = value
        changes.append({**item, "new": catalog.show(s, value), "value": value,
                        "problem": None})
    try:
        catalog.check_together(in_force)
    except SettingError as e:
        changes.append({"key": "", "label": "Together", "now": "", "new": "",
                        "problem": str(e)})
    return changes
