"""
CSP DocMaker — which sheet column is which field (PROJECT-REGISTER No. 211,
Stage 4: TK-029, ZU-04)

Eko's column names are the starting point (csp_mapping.SHEET_COLUMN_TO_FIELD).
A workspace whose sheet calls them something else ("Agent Code", "Phone")
sets its own names on Setup → Columns. The app GUESSES them from the sheet's
headings, with fixed rules — no AI (No. 116):

  1.0  the heading is Eko's name for the field                  "sure"
  0.9  the heading is a known other name for it ("Phone")       "sure"
  0.7  the heading contains a known name ("CSP Mobile No.")     "likely"

Each heading is given to one field at most; the Super Admin only confirms
or corrects, then saves. Saved names live in workspace_settings
"column_map" = {field: heading} (only those that differ from Eko's).
"""

import logging
import re
from typing import Dict, List, Optional

from app.services import csp_mapping

logger = logging.getLogger(__name__)

SYNONYMS: Dict[str, tuple] = {
    "csp_code": ("code", "csp code", "agent code", "kiosk code", "bc code",
                 "csp id", "agent id", "outlet code"),
    "name": ("name", "csp name", "agent name", "full name", "outlet name"),
    "mobile": ("mobile", "mobile number", "mobile no", "phone",
               "phone number", "contact number", "contact no", "whatsapp"),
    "email": ("email", "email id", "e mail", "mail", "email address"),
    "address": ("address", "shop address", "business address", "location"),
    "district": ("district", "distt", "city"),
    "state": ("state",),
    "branch_name": ("branch", "branch name", "home branch"),
    "branch_code": ("branch code", "sol", "sol id", "branch id"),
    "ao": ("ao", "area office"),
    "lho": ("lho", "circle", "zone"),
    "dc": ("dc", "district coordinator", "coordinator"),
    "rm_name": ("rm", "relationship manager", "manager", "rm name",
                "field officer"),
    "asm_name": ("asm", "area sales manager"),
    "rbo_name": ("rbo", "rbo name", "region"),
    "gender": ("gender", "sex"),
    "photo_url": ("photo", "picture", "image", "photograph"),
}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def fields() -> List[dict]:
    """Every field a sheet column can fill, with Eko's heading."""
    out = []
    for header, field in csp_mapping.SHEET_COLUMN_TO_FIELD.items():
        out.append({"field": field, "eko_header": header,
                    "label": _label(field)})
    return out


def _label(field: str) -> str:
    from app.services import field_ownership as fo
    try:
        return fo.label_of(field)
    except Exception:
        return field.replace("_", " ").title()


def guess(headers: List[str]) -> Dict[str, dict]:
    """{field: {"header", "score", "how"}} for the fields found."""
    eko = {_norm(h): f for h, f in csp_mapping.SHEET_COLUMN_TO_FIELD.items()}
    candidates = []
    for header in headers:
        n = _norm(header)
        if not n:
            continue
        if n in eko:
            candidates.append((1.0, len(n), eko[n], header, "same name as Eko's"))
            continue
        for field, names in SYNONYMS.items():
            for name in names:
                if n == name:
                    candidates.append((0.9, len(name), field, header,
                                       "a usual name for it"))
                elif f" {name} " in f" {n} ":
                    candidates.append((0.7, len(name), field, header,
                                       f"contains “{name}”"))
    candidates.sort(key=lambda c: (-c[0], -c[1]))
    taken_fields, taken_headers, out = set(), set(), {}
    for score, _, field, header, how in candidates:
        if field in taken_fields or header in taken_headers:
            continue
        taken_fields.add(field)
        taken_headers.add(header)
        out[field] = {"header": header, "score": score, "how": how}
    return out


def to_store(chosen: Dict[str, Optional[str]]) -> Dict[str, str]:
    """Only the fields whose heading differs from Eko's are kept."""
    eko = {f: h for h, f in csp_mapping.SHEET_COLUMN_TO_FIELD.items()}
    out = {}
    for field, header in chosen.items():
        if field not in eko:
            raise ValueError(f"There is no field {field!r}.")
        header = (header or "").strip()
        if header and _norm(header) != _norm(eko[field]):
            out[field] = header
    seen = {}
    for field, header in out.items():
        if _norm(header) in seen:
            raise ValueError(f"“{header}” is chosen for both "
                             f"{_label(seen[_norm(header)])} and "
                             f"{_label(field)}.")
        seen[_norm(header)] = field
    return out


def main_headers() -> List[str]:
    """The headings of this workspace's main tab (raises if unreadable)."""
    from app.config import get_settings
    from app.services import sheet_admin_service as sheets
    s = get_settings()
    if not s.google_sheets_csp_sheet_id:
        raise ValueError("Connect your main CSP sheet first (Setup → "
                         "Connections).")
    return [h for h in sheets._header(s.google_sheets_csp_sheet_id,
                                      s.google_sheets_csp_sheet_name) if h]


async def describe(session) -> dict:
    own = csp_mapping.column_map()
    rows = []
    for f in fields():
        rows.append({**f, "header": own.get(f["field"], f["eko_header"]),
                     "own": f["field"] in own})
    return {"fields": rows, "own": own}


async def save(session, chosen: Dict[str, Optional[str]], user,
               via: str = "screen") -> dict:
    from sqlalchemy import select
    from app.models.workspace_setting import WorkspaceSetting
    from app.services import workspace_settings
    store = to_store(chosen)
    ws = await workspace_settings._workspace(session)
    row = (await session.execute(select(WorkspaceSetting).where(
        WorkspaceSetting.key == "column_map"))).scalars().first()
    old = row.value if row is not None else None
    if (old or {}) == store:
        return await describe(session)
    who = ((user or {}).get("sub") or "").lower()
    if not store:
        if row is not None:
            await session.delete(row)
    elif row is None:
        session.add(WorkspaceSetting(workspace_id=ws.id, key="column_map",
                                     value=store, updated_by=who))
    else:
        row.value, row.updated_by = store, who
    await workspace_settings._record(session, ws, "column_map", old,
                                     store or None, user, via)
    await session.commit()
    workspace_settings.forget(ws.id)
    logger.info("data_shape: %s set %d own column name(s) in %s", who,
                len(store), ws.slug)
    return await describe(session)
