"""
CSP DocMaker — Eko's CSPs from the Calling and Lead raw data sheets (No. 121)

Asked for 21 Oct 2026, Eko SBI Kiosk CSP workspace only:

  * Calling sheet  = CSPs already working (OLD). "Terminal Status" Inactive
    (or empty) → nothing is sent to them.
  * Lead raw data  = CSPs being onboarded. "Remarks" = "Go Live Done" means
    live; anything else means still pending → nothing is sent to them.
  * When a Lead row changes to "Go Live Done", it is copied into CSPDATA
    (KOData / SUBKOData by code length), blanks filled from Zoho Leads (the
    Lead must match the mobile number AND the name or branch code), and the
    usual new-CSP flow makes and emails the documents.

Decided with the user the same day:
  * the CSPs already live when this starts are not new (no mail);
  * a CSP in the Calling sheet is old even when it then goes live — and
    while its Lead row is not live, the Lead sheet wins: nothing is sent;
  * Calling-sheet CSPs are copied into CSPDATA as old;
  * an empty Terminal Status is treated like Inactive; a code that is not
    8–10 letters/digits is skipped and reported;
  * a KOData cell someone already filled is never overwritten (only new
    rows are added).

Runs every SOURCE_SHEETS_INTERVAL_MINUTES. Reads both sheets (Viewer access
is enough), writes only to CSPDATA. Off when the sheet ids are not set.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select

from app.config import get_settings

logger = logging.getLogger(__name__)

CODE = re.compile(r"^[A-Z0-9]{8,10}$")
ACTIVE = "active"

# KOData column  <-  Calling sheet column   (agreed 21 Oct 2026)
FROM_CALLING = {
    "CSP Code": "CSP ID",
    "CSP Name": "CSP Name",
    "CSP Mobile Number": "CSP Mobile number",
    "CSP Email Id": "CSP Mail ID",
    "Gender": "Gender",
    "Branch Name": "Branch Name",
    "Branch Code": "Branch Code",
    "Address": "Full Address",
    "District": "District",
    "State": "State",            # the sheet has two; the fuller (later) one
    "AO": "AO",
    "DC": "District Coordinator",
    "DC Email Id": "Email ID DC",
    "DC Contact Number": "Mobile Number DC",
    "LHO": "Circle (LHO)",
    "Relationship Manager (RM)": "Relationship Manager",
    "RBO Name": "RBO",
}
# KOData column  <-  Lead raw data column
FROM_LEAD = {
    "CSP Code": "CSP Code",
    "CSP Name": "CSP Name",
    "CSP Mobile Number": "Mobile No.",
    "Gender": "Gender",
    "Branch Name": "Branch Name",
    "Branch Code": "Branch Code",
    "Branch Contact Number": "Branch Contact No.",
    "District": "District",
    "State": "State",
    "AO": "AO",
    "LHO": "LHO",
    "Relationship Manager (RM)": "Owner (RM)",
    "ASM": "ASM",
    "RBO Name": "RBO Name",
    "RBO Contact No.": "RBO Contact No.",
}
# KOData column  <-  Zoho Lead field, used only for blanks of a NEW CSP.
FROM_ZOHO = {
    "CSP Name": ("Full_Name",),
    "CSP Mobile Number": ("Mobile", "Phone"),
    "CSP Email Id": ("Email",),
    # The "Shop Address with Shop Name" box, else the Business Address
    # section (asked 22 Oct 2026): zoho_client.lead_address.
    "Address": ("Shop / Business Address",),
    "State": ("States",),
}


def code_of(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def read_rows(spreadsheet_id: str, tab: str, header_row: int) -> List[dict]:
    """Every non-empty row as {header: value}. With repeated headers the
    LAST column wins (the Calling sheet's fuller "State")."""
    from app.services import sheet_admin_service as sheets
    try:
        values = sheets._service().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=sheets._quote_tab(tab)).execute().get("values", [])
    except Exception as e:
        sheets._reset()
        raise sheets.SheetAdminError(
            f"Could not read {tab!r}: {type(e).__name__}: {e}") from e
    if len(values) < header_row:
        return []
    header = [str(h).strip() for h in values[header_row - 1]]
    out = []
    for raw in values[header_row:]:
        if not any(str(c).strip() for c in raw):
            continue
        row = {}
        for i, h in enumerate(header):
            if h:
                row[h] = str(raw[i]).strip() if i < len(raw) else ""
        out.append(row)
    return out


def mapped(row: dict, mapping: Dict[str, str]) -> Dict[str, str]:
    return {ko: row.get(src, "").strip() for ko, src in mapping.items()
            if row.get(src, "").strip()}


# ---- the temporary Address tab (No. 129) -------------------------------------

def address_map() -> Optional[Dict[str, str]]:
    """{CSP code: address} from the Address tab, or None when there is no
    such tab (it is there for about a week, 21 Oct 2026). Columns are found
    by name: the first heading with "code" and the first with "address"."""
    from app.services import sheet_admin_service as sheets
    s = get_settings()
    sid = s.address_sheet_id or s.google_sheets_csp_sheet_id
    titles = [t["title"] for t in sheets.list_tabs(sid)]
    if s.address_sheet_tab not in titles:
        return None
    rows = read_rows(sid, s.address_sheet_tab, 1)
    if not rows:
        return {}
    heads = list(rows[0].keys())
    code_h = next((h for h in heads if "code" in h.lower()), None)
    addr_h = next((h for h in heads if "address" in h.lower()), None)
    if not code_h or not addr_h:
        raise sheets.SheetAdminError(
            f"The {s.address_sheet_tab!r} tab needs a CSP Code column and an "
            f"Address column; it has: {', '.join(heads)}")
    return {code_of(r.get(code_h)): r.get(addr_h, "").strip()
            for r in rows if code_of(r.get(code_h)) and r.get(addr_h, "").strip()}


def fill_blank_addresses(addresses: Dict[str, str], codes: set) -> List[str]:
    """Write the Address-tab address into KOData / SUBKOData for these codes
    — only where the Address cell is EMPTY, in one request per tab. Returns
    the codes written. Rows of CSPs not in `codes` are never touched."""
    from app.services import sheet_admin_service as sheets
    s = get_settings()
    written = []
    for tab in (s.google_sheets_csp_sheet_name, s.google_sheets_subko_sheet_name):
        try:
            values = sheets._service().spreadsheets().values().get(
                spreadsheetId=s.google_sheets_csp_sheet_id,
                range=sheets._quote_tab(tab)).execute().get("values", [])
        except Exception as e:
            sheets._reset()
            if tab == s.google_sheets_csp_sheet_name:
                raise sheets.SheetAdminError(
                    f"Could not read {tab!r}: {type(e).__name__}: {e}") from e
            continue
        if not values:
            continue
        header = [str(h).strip().lower() for h in values[0]]
        if "csp code" not in header or "address" not in header:
            continue
        ci, ai = header.index("csp code"), header.index("address")
        data = []
        for n, row in enumerate(values[1:], start=2):
            code = code_of(row[ci] if ci < len(row) else "")
            current = str(row[ai]).strip() if ai < len(row) else ""
            if code in codes and not current and addresses.get(code):
                data.append({"range": f"{sheets._quote_tab(tab)}!"
                                      f"{sheets.column_letter(ai)}{n}",
                             "values": [[addresses[code]]]})
                written.append(code)
        if data:
            sheets._service().spreadsheets().values().batchUpdate(
                spreadsheetId=s.google_sheets_csp_sheet_id,
                body={"valueInputOption": "RAW", "data": data}).execute()
    return written


def rbo_name(cells: Dict[str, str], lead_row: Optional[dict]) -> None:
    """The Calling sheet's "RBO" column holds the RBO's NUMBER (2, 3, …),
    not its name (seen 21 Oct 2026): Lead raw data's "RBO Name" wins; a bare
    number becomes "RBO 3"."""
    name = (lead_row or {}).get("RBO Name", "").strip()
    if name:
        cells["RBO Name"] = name
    elif cells.get("RBO Name", "").isdigit():
        cells["RBO Name"] = f"RBO {cells['RBO Name']}"


def hold_reason(in_calling: bool, calling_status: str, in_lead: bool,
                lead_live: bool, lead_remarks: str) -> Optional[str]:
    """Why nothing may be sent, or None. The Lead sheet wins while not live
    (decided 21 Oct 2026)."""
    if in_lead and not lead_live:
        return ("Not live yet in the Lead raw data sheet"
                + (f" (Remarks: {lead_remarks})" if lead_remarks else "")
                + " — nothing is sent until it says "
                + f"\"{get_settings().lead_live_remark}\".")
    if in_calling and (calling_status or "").strip().lower() != ACTIVE:
        return ("Inactive in the Calling sheet" if calling_status else
                "No Terminal Status in the Calling sheet") + \
            " — nothing is sent until it is Active."
    return None


def zoho_fill(cells: Dict[str, str]) -> Dict[str, str]:
    """Fill a NEW CSP's blank columns from its Zoho Lead. Returns what was
    filled ({column: Zoho field}); cells is changed in place. A Lead is used
    only when the mobile number AND the name or branch code agree
    (zoho_client.find_lead). Never raises: a Zoho failure leaves the blanks
    for the CSP to be asked about, and is logged."""
    from app.services import zoho_client
    blanks = [c for c in FROM_ZOHO if not cells.get(c)]
    if not blanks or not zoho_client.is_configured():
        return {}
    phone = cells.get("CSP Mobile Number", "")
    if not phone:
        return {}
    try:
        lead = zoho_client.find_lead(phone, cells.get("CSP Name", ""),
                                     cells.get("Branch Code", ""))
    except Exception as e:
        logger.error("source_sheets.zoho_fill: Zoho Lead search failed for "
                     "CSP %s: %s: %s", cells.get("CSP Code"),
                     type(e).__name__, e, exc_info=True)
        return {}
    if not lead:
        logger.info("source_sheets.zoho_fill: no matching Zoho Lead for CSP "
                    "%s", cells.get("CSP Code"))
        return {}
    filled = {}
    for column in blanks:
        for key in FROM_ZOHO[column]:
            value = zoho_client.lead_field(lead, key)
            if value:
                cells[column] = value
                filled[column] = key
                break
    filled["_lead_id"] = str(lead.get("id", ""))
    return filled


@dataclass
class Summary:
    first_run: bool = False
    calling_rows: int = 0
    lead_rows: int = 0
    went_live: List[str] = field(default_factory=list)
    imported_new: List[str] = field(default_factory=list)
    imported_old: int = 0
    held: int = 0
    addresses_filled: int = 0
    skipped: List[str] = field(default_factory=list)

    def text(self) -> str:
        return (f"{'baseline; ' if self.first_run else ''}"
                f"Calling {self.calling_rows} rows, Lead {self.lead_rows} "
                f"rows; went live {len(self.went_live)}; added to CSPDATA: "
                f"{len(self.imported_new)} new, {self.imported_old} old; "
                f"{self.held} on hold; {self.addresses_filled} address(es) "
                f"from the Address tab; skipped {len(self.skipped)}")


def run(session) -> Summary:
    """One pass, in the Eko workspace (sync session; the worker sets the
    workspace). Raises when a sheet cannot be read — nothing is changed then."""
    from app.models.csp_record import CSPRecord
    from app.models.source_sheet import SourceSheetState
    from app.services import sheet_admin_service as sheets

    s = get_settings()
    summary = Summary()
    calling = read_rows(s.calling_sheet_id, s.calling_sheet_tab,
                        s.calling_header_row)
    lead = read_rows(s.lead_sheet_id, s.lead_sheet_tab, s.lead_header_row)
    summary.calling_rows, summary.lead_rows = len(calling), len(lead)

    # What CSPDATA already holds (never overwritten).
    in_data = set()
    for tab in (s.google_sheets_csp_sheet_name,
                s.google_sheets_subko_sheet_name):
        try:
            for r in read_rows(s.google_sheets_csp_sheet_id, tab, 1):
                if code_of(r.get("CSP Code")):
                    in_data.add(code_of(r.get("CSP Code")))
        except sheets.SheetAdminError as e:
            if tab == s.google_sheets_csp_sheet_name:
                raise
            logger.warning("source_sheets: %s not read: %s", tab, e)

    live_word = s.lead_live_remark.strip().lower()
    by_calling, by_lead = {}, {}
    for r in calling:
        c = code_of(r.get("CSP ID"))
        if not c:
            continue
        if not CODE.match(c):
            summary.skipped.append(f"Calling sheet: code {c!r} is not 8–10 "
                                   "letters/digits")
            continue
        by_calling[c] = r
    for r in lead:
        c = code_of(r.get("CSP Code"))
        if not c:
            continue        # not given a code yet: nothing to do
        if not CODE.match(c):
            summary.skipped.append(f"Lead raw data: code {c!r} is not 8–10 "
                                   "letters/digits")
            continue
        by_lead[c] = r

    # The temporary Address tab (No. 129): None when it is not there.
    addresses = None
    try:
        addresses = address_map()
    except sheets.SheetAdminError as e:
        logger.error("source_sheets: the Address tab could not be read: %s", e)

    states = {st.csp_code: st for st in session.execute(
        select(SourceSheetState)).scalars().all()}
    summary.first_run = not states
    now = datetime.now(timezone.utc)

    for c in sorted(set(by_calling) | set(by_lead)):
        st = states.get(c)
        if st is None:
            st = SourceSheetState(csp_code=c)
            session.add(st)
            states[c] = st
            previously_live = None
        else:
            previously_live = st.lead_live
        crow, lrow = by_calling.get(c), by_lead.get(c)
        st.in_calling = crow is not None
        st.calling_status = (crow or {}).get("Terminal Status", "") or None
        st.in_lead = lrow is not None
        st.lead_remarks = ((lrow or {}).get("Remarks", "") or None)
        st.lead_live = bool(lrow) and (lrow.get("Remarks", "").strip().lower()
                                       == live_word)
        if summary.first_run:
            st.baseline_live = st.lead_live
        elif (st.lead_live and previously_live is not True
              and not st.baseline_live and st.went_live_at is None):
            st.went_live_at = now
            summary.went_live.append(c)
        st.hold_reason = hold_reason(st.in_calling, st.calling_status or "",
                                     st.in_lead, st.lead_live,
                                     st.lead_remarks or "")
        if st.hold_reason:
            summary.held += 1

    # Rows to add to CSPDATA, grouped by tab.
    to_add: Dict[str, List[dict]] = {}
    added: List[tuple] = []

    def plan(c: str, cells: Dict[str, str], origin: str):
        rbo_name(cells, by_lead.get(c))
        if (origin == "baseline" and addresses and addresses.get(c)
                and not cells.get("Address")):
            cells["Address"] = addresses[c]
        if not cells.get("CSP Name"):
            summary.skipped.append(f"{c}: no CSP Name — not added to CSPDATA")
            return
        to_add.setdefault(s.csp_tab_for(c), []).append(cells)
        added.append((c, origin))

    for c in summary.went_live:
        st = states[c]
        if c in in_data or st.imported_as:
            continue
        if c in by_calling:
            # In the Calling sheet: old, even now that it is live.
            cells = {**mapped(by_lead[c], FROM_LEAD),
                     **mapped(by_calling[c], FROM_CALLING)}
            plan(c, cells, "baseline")
        else:
            cells = mapped(by_lead[c], FROM_LEAD)
            filled = zoho_fill(cells)
            st.zoho_filled = filled or None
            plan(c, cells, "new")

    went = set(summary.went_live)
    for c, crow in by_calling.items():
        st = states[c]
        if c in in_data or st.imported_as or c in went:
            continue
        cells = mapped(crow, FROM_CALLING)
        if c in by_lead:   # the Lead sheet may know what the Calling sheet lacks
            cells = {**mapped(by_lead[c], FROM_LEAD), **cells}
        plan(c, cells, "baseline")
    for c, lrow in by_lead.items():
        # Live before this started and not in the Calling sheet: old too.
        st = states[c]
        if (st.baseline_live and c not in by_calling and c not in in_data
                and not st.imported_as):
            plan(c, mapped(lrow, FROM_LEAD), "baseline")

    for tab, rows in to_add.items():
        sheets.append_rows(s.google_sheets_csp_sheet_id, tab, rows)
    for c, origin in added:
        states[c].imported_as = origin
        states[c].imported_at = now
        if origin == "new":
            summary.imported_new.append(c)
        else:
            summary.imported_old += 1

    # Old CSPs copied in earlier: their EMPTY Address cells from the tab.
    # CSPs that were in CSPDATA before this job never are (21 Oct 2026).
    if addresses is not None:
        from app.models.sync_run import SyncRun
        copied = {c for c, st in states.items() if st.imported_as == "baseline"}
        filled = fill_blank_addresses(addresses, copied)
        summary.addresses_filled = len(filled)
        session.add(SyncRun(source="address", status="completed",
                            is_baseline=False, rows_read=len(addresses),
                            updated_count=len(filled),
                            finished_at=now))
        fill = {c: addresses[c] for c in filled}
    else:
        fill = {}

    # The hold, on every CSP the app already has.
    for csp in session.execute(select(CSPRecord)).scalars().all():
        st = states.get(code_of(csp.csp_id))
        if st is not None and csp.send_hold != st.hold_reason:
            csp.send_hold = st.hold_reason
        if code_of(csp.csp_id) in fill and not (csp.address or "").strip():
            csp.address = fill[code_of(csp.csp_id)]   # the sync agrees next run
    session.commit()
    for line in summary.skipped:
        logger.warning("source_sheets: skipped — %s", line)
    logger.info("source_sheets: %s", summary.text())
    return summary


def state_for_new_record(session, code: str):
    """For the sheet sync: (origin, hold) for a CSP it is about to create,
    from what this job recorded — or (None, None) if this job never saw it."""
    from app.models.source_sheet import SourceSheetState
    st = session.execute(select(SourceSheetState).where(
        SourceSheetState.csp_code == code_of(code))).scalars().first()
    if st is None:
        return None, None
    return st.imported_as, st.hold_reason
