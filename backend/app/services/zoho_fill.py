"""
CSP DocMaker — fill a CSP's blanks from Zoho before asking them (No. 124)

Asked for 21 Oct 2026: "read any missing info from Zoho; only if it is not
there, alert the CSP on WhatsApp." Zoho's TYPED Lead fields were entered by
Eko's onboarding team, so they are used like the sheets: written into
CSPDATA (the sheet is the source of truth — a value set only in the app
would be wiped by the next sync) and onto the record. Only blank fields are
filled; nothing anyone entered is replaced.

The address comes from the Lead's "Shop Address with Shop Name" box, or
else its Business Address section (asked 22 Oct 2026) — never from the
attached documents, which are not read.

Eko workspace only (the Zoho account is Eko's). Never raises: if Zoho or
the sheet fails, nothing is filled, the reason is logged, and the CSP is
asked as before.
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# CSP record field  <-  Zoho Lead fields, first filled one wins
FROM_ZOHO = {
    "email": ("Email",),
    "address": ("Shop / Business Address",),  # zoho_client.lead_address
    "state": ("States",),
    "gender": ("Gender",),
}


def _is_eko(session) -> bool:
    from sqlalchemy import select

    from app.models.workspace import DEFAULT_SLUG, Workspace
    from app.workspace_context import current_workspace_id
    wid = current_workspace_id()
    if wid is None:
        return False
    slug = session.execute(select(Workspace.slug).where(
        Workspace.id == wid)).scalar()
    return slug == DEFAULT_SLUG


def fill_from_zoho(session, record) -> Dict[str, str]:
    """Blank fields of this CSP filled from their Zoho Lead's typed fields.
    Returns {field: value} actually filled (written to the sheet and the
    record), or {} when nothing could be filled."""
    from app.services import sheet_writeback_service as wb
    from app.services import zoho_client

    blanks = [f for f in FROM_ZOHO
              if not (getattr(record, f, None) or "").strip()]
    if not blanks or not zoho_client.is_configured() or not _is_eko(session):
        return {}
    if not (record.mobile or "").strip():
        return {}
    try:
        lead = zoho_client.find_lead(record.mobile, record.name or "",
                                     record.branch_code or "")
    except Exception as e:
        logger.error("zoho_fill: Zoho search failed for %s: %s: %s",
                     record.csp_id, type(e).__name__, e, exc_info=True)
        return {}
    if not lead:
        return {}
    found = {}
    for f in blanks:
        for key in FROM_ZOHO[f]:
            value = zoho_client.lead_field(lead, key)
            if value:
                found[f] = value
                break
    if not found:
        return {}
    try:
        written, skipped = wb.write_values(record.csp_id, found)
    except Exception as e:
        logger.error("zoho_fill: %s — found %s in Zoho but the sheet could "
                     "not be updated, so nothing was filled: %s: %s",
                     record.csp_id, sorted(found), type(e).__name__, e,
                     exc_info=True)
        return {}
    filled = {f: v for f, v in found.items() if f in (written or {})}
    for f, v in filled.items():
        setattr(record, f, v)
    if filled:
        logger.info("zoho_fill: %s — filled %s from Zoho Lead %s",
                    record.csp_id, sorted(filled), lead.get("id"))
        _record_provenance(session, record.csp_id, filled, lead)
    return filled


def _record_provenance(session, csp_id: str, filled: Dict[str, str],
                       lead: dict) -> None:
    """Keep where each value came from (No. 146). The values are already
    in the sheet; failing to note their source must not undo that."""
    from app.services import field_quality
    try:
        with session.begin_nested():
            for f, v in filled.items():
                field_quality.record_fill(
                    session, csp_id, f, v, "zoho",
                    f"Zoho Lead {lead.get('id', '')}: {FROM_ZOHO[f][0]}")
    except Exception as e:
        logger.error("zoho_fill: %s — filled %s from Zoho but could not "
                     "record where they came from: %s: %s", csp_id,
                     sorted(filled), type(e).__name__, e, exc_info=True)
