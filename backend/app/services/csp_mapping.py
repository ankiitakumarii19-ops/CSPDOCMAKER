"""
CSP DocMaker — Canonical CSP Mapping

One place where the three vocabularies meet:

    Google Sheet column  →  CSPRecord field  →  template placeholder value

Everything downstream (sync, missing-data checks, document generation,
validation, email, dashboard) reads canonical field names from here, so a
sheet column is named in exactly one place.

The sheet columns below are the actual headers of the 'CSPDATA' sheet, tab
Sheet1. Nothing here is inferred: a header that is not listed is ignored, and
a template value that has no sheet column is either computed (the certificate
dates) or reported as missing data.
"""

import logging
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType

logger = logging.getLogger(__name__)


# ---- Google Sheet header → CSPRecord attribute -------------------------
# Matching ignores case and surrounding whitespace.
SHEET_COLUMN_TO_FIELD: Dict[str, str] = {
    "CSP Code": "csp_code",
    "CSP Name": "name",
    "CSP Mobile Number": "mobile",
    "CSP Email Id": "email",
    "Branch Name": "branch_name",
    "Branch Code": "branch_code",
    "Address": "address",
    "District": "district",
    "State": "state",
    "AO": "ao",
    "LHO": "lho",
    "DC": "dc",
    "DC Email Id": "dc_email",
    "DC Contact Number": "dc_contact",
    "Relationship Manager (RM)": "rm_name",
    "ASM": "asm_name",
    "ASM Email Id": "asm_email",
    "ASM Contact Number": "asm_contact",
    "RBO Name": "rbo_name",
    "Photo": "photo_url",
    # No template prints these three, but every one of them is chased when
    # blank — Gender from the CSP, the other two from their RM — and whatever
    # comes back is written to the sheet. An unmapped column could be neither.
    "Gender": "gender",
    "Branch Contact Number": "branch_contact",
    "RBO Contact No.": "rbo_contact",
    # Which documents the CSP says they already hold. These four columns do
    # not exist in the sheet yet — they are added when the CSP form goes
    # live. An absent header is simply ignored by map_sheet_row, so naming
    # them here early is safe.
    "Has CSP ID Card": "has_id_card",
    "Has CSP Certificate": "has_csp_certificate",
    "Has Training Certificate": "has_training_certificate",
    "Has BCP": "has_bcp",
}

# Every sheet column now maps to a field. Kept so a future column that is
# genuinely ignored has a documented home rather than being silently dropped.
UNUSED_SHEET_COLUMNS = ()

# The sheet has no separate CSP ID column, so 'CSP Code' is the business key.
IDENTITY_FIELD = "csp_code"


# ---- Canonical template field → CSPRecord attribute --------------------
# Keys are the canonical names used in template_service.PLACEHOLDER_FIELDS.
FIELD_TO_CSP_ATTR: Dict[str, str] = {
    "csp_name": "name",
    "csp_code": "csp_code",
    "branch_name": "branch_name",
    "branch_code": "branch_code",
    "address": "address",
    "mobile": "mobile",
    "email": "email",
    "district": "district",
    "state": "state",
    # The BCP prints the AO value in its "Module" row.
    "ao": "ao",
    "rbo_name": "rbo_name",
    "asm_name": "asm_name",
    "asm_email": "asm_email",
    "asm_contact": "asm_contact",
    "photo": "photo_url",
    # Not a placeholder: no template prints a gender. It is carried so the
    # salutation before the CSP's name can be the one that applies to them.
    "gender": "gender",
}

# Generated at document time rather than read from the CSP record.
COMPUTED_FIELDS = ("certificate_date", "certificate_month_year")

# Labels shown to an RM in the missing-data screen, and the input type.
FIELD_LABELS: Dict[str, tuple] = {
    "csp_name": ("CSP Name", "text"),
    "csp_code": ("CSP Code", "text"),
    "branch_name": ("Branch Name", "text"),
    "branch_code": ("Branch Code", "text"),
    "address": ("Address", "address"),
    "mobile": ("CSP Mobile Number", "phone"),
    "email": ("CSP Email Id", "email"),
    "district": ("District", "text"),
    "state": ("State", "text"),
    "ao": ("AO", "text"),
    "rbo_name": ("RBO Name", "text"),
    "asm_name": ("ASM", "text"),
    "asm_email": ("ASM Email Id", "email"),
    "asm_contact": ("ASM Contact Number", "phone"),
    "photo": ("Photo", "photo"),
    "certificate_date": ("Certificate made date", "date"),
}

# CSPRecord attribute → the sheet column it came from. The inverse of
# SHEET_COLUMN_TO_FIELD, used when writing a correction back to the sheet.
FIELD_TO_SHEET_COLUMN: Dict[str, str] = {
    field: column for column, field in SHEET_COLUMN_TO_FIELD.items()
}


def normalize_header(header: str) -> str:
    return header.strip().lower()


_NORMALIZED_COLUMNS = {normalize_header(k): v for k, v in SHEET_COLUMN_TO_FIELD.items()}


def map_sheet_row(row: Dict[str, str]) -> Dict[str, str]:
    """Map one sheet row (header → value) to CSPRecord field names.

    Unknown headers are ignored. Values are stripped. Empty cells are kept as
    empty strings so the sync can tell "cleared in the sheet" from "absent".
    """
    mapped: Dict[str, str] = {}
    for header, value in row.items():
        field = _NORMALIZED_COLUMNS.get(normalize_header(header))
        if field:
            mapped[field] = (value or "").strip()
    return mapped


def csp_id_from_row(mapped: Dict[str, str]) -> Optional[str]:
    """The business key for a mapped row, or None when it cannot be identified."""
    value = (mapped.get(IDENTITY_FIELD) or "").strip()
    return value or None


def document_values(
    csp: CSPRecord,
    certificate_date_value: Optional[date] = None,
) -> Dict[str, str]:
    """Canonical field → value for filling a template.

    Args:
        csp: The CSP record.
        certificate_date_value: The date printed on the certificates. Defaults
            to the record's stored certificate_date.
    """
    from app.services import document_service  # local import avoids a cycle

    values: Dict[str, str] = {}
    for field, attr in FIELD_TO_CSP_ATTR.items():
        raw = getattr(csp, attr, None)
        value = "" if raw is None else str(raw).strip()
        if field in TITLE_CASED_FIELDS:
            value = title_case(value)
        values[field] = value

    made_on = effective_certificate_date(csp, certificate_date_value)
    if made_on is not None:
        values["certificate_date"] = document_service.certificate_date(made_on)
        values["certificate_month_year"] = document_service.certificate_month_year(made_on)
    else:
        values["certificate_date"] = ""
        values["certificate_month_year"] = ""
    return values


def effective_certificate_date(csp, explicit=None):
    """The date a certificate carries: the day it is being made.

    Confirmed rule, and it is that simple — a document made today is dated
    today, whoever it is for. An existing CSP is not asked to remember when
    they were onboarded, and their RM is not asked to supply a date before
    anything can be issued.

    Two narrower cases come first:

      * an explicit date, when a caller is deliberately setting one;
      * a date already on the record, so a CSP whose documents were issued
        on a particular day keeps that day if anything is reissued, and
        their ID card and certificate never disagree.

    Otherwise: today. This never returns None, so a missing date can no
    longer block a document from being made.
    """
    from datetime import date as _date

    if explicit:
        return explicit
    if getattr(csp, "certificate_date", None):
        return csp.certificate_date
    return _date.today()


def required_fields_for(doc_type: DocumentType) -> list:
    """Canonical fields an RM must supply before this document can be made.

    Derived from the template itself, minus the values generated at document
    time — except certificate_date, which an existing CSP's RM provides.
    """
    from app.services import template_service

    from app.config import get_settings

    fields = set(template_service.PLACEHOLDER_FIELDS[doc_type].values())
    if not get_settings().photo_placeholder_allowed:
        # While placeholder photos are allowed the document can still be
        # produced without a CRM photo, so it is not "missing data".
        fields |= set(template_service.IMAGE_FIELDS.get(doc_type, ()))
    # certificate_month_year is always derived from certificate_date.
    fields.discard("certificate_month_year")
    if "certificate_date" not in fields and doc_type in (
        DocumentType.BCP,
    ):
        # The BCP prints month+year, which still comes from the same date.
        fields.add("certificate_date")
    return sorted(fields)


# ---- trimming an address that repeats what is printed beside it ---------
#
# The CSP Certificate prints the address and then "DIST- <district>,
# <state>" after it. CSPs write their address the way people do, ending
# with the district, state and pincode, so the line came out as:
#
#   Samvapur belghat gorakhpur up 273404, DIST- Gorakhpur, Uttar Pradesh
#
# Only the tail of the address is trimmed, never the middle. A district
# that appears at the START of an address is part of the place name —
# "Patna City Main Road" in Patna district must keep its first word — and
# the only safe way to tell the two apart is position.

_PINCODE = r"\d{6}"
_SEPARATORS = r"[\s,.\-–—]*"

# Words people put in front of a district or a pincode. Deliberately short:
# a wrong entry here silently eats part of somebody's address.
_ADDRESS_FILLER = ("district", "distt", "dist", "pin code", "pincode", "pin")


def _phrase(text: str) -> str:
    """A regex matching this phrase, tolerant of the spacing between words."""
    return r"\b" + r"\s+".join(re.escape(w) for w in text.split()) + r"\b"


def _state_patterns(state: str) -> List[str]:
    """The state's name, and its initials when it has more than one word.

    'Uttar Pradesh' is written 'up' about as often as it is written out.
    Initials are only used for multi-word states — a single letter for
    'Bihar' would match far too much.
    """
    state = (state or "").strip()
    if not state:
        return []
    patterns = [_phrase(state)]
    words = state.split()
    if len(words) > 1:
        patterns.append(r"\b" + "".join(w[0] for w in words).lower() + r"\b")
    return patterns


def address_without_district_state(address: str, *, district: str = "",
                                   state: str = "") -> str:
    """The address with a trailing district, state and pincode removed.

    Returns the address unchanged when nothing matches, and never returns
    an empty string: an address that is *only* its district and pincode is
    left alone, because printing nothing would be worse than repeating
    something.
    """
    original = (address or "").strip()
    if not original:
        return original

    patterns = (
        [_PINCODE]
        + _state_patterns(state)
        + ([_phrase(district)] if (district or "").strip() else [])
        + [_phrase(f) for f in _ADDRESS_FILLER]
    )

    text = original
    for _ in range(12):            # each pass peels one layer off the end
        changed = False
        for pattern in patterns:
            match = re.search(
                _SEPARATORS + "(?:" + pattern + ")" + _SEPARATORS + "$",
                text, re.IGNORECASE)
            # start() == 0 would consume the whole address.
            if match and match.start() > 0:
                candidate = text[:match.start()].strip(" ,.-–—")
                if candidate:
                    text = candidate
                    changed = True
        if not changed:
            break

    return text or original


# ---- how a value is printed ---------------------------------------------
#
# Names, places and addresses are typed into the sheet however the person
# typing felt at the time: 'ANIRUDH KUMAR KUSHWAHA', 'jayprakash',
# 'Mukesh kumar singhi'. On a certificate they should all read the same
# way, so every word is capitalised on the way out.
#
# Codes, numbers and email addresses are left exactly as they are. A CSP
# code is an identifier, and 'Jayprakash@Example.Com' would be wrong.
#
# This changes only what is PRINTED. What is stored stays as the CSP or
# the RM typed it, so nothing is quietly rewritten in the sheet.
TITLE_CASED_FIELDS: Tuple[str, ...] = (
    "csp_name", "branch_name", "address", "district", "state",
    "ao", "rbo_name", "asm_name",
)

# The first letter of a word, where a word starts at the beginning or
# after a space, hyphen, slash, bracket, comma or full stop — but NOT
# after an apostrophe, which would turn "don't" into "Don'T".
_WORD_START = re.compile(r"(^|[\s\-/(\[.,])([a-z])")


def title_case(text: str) -> str:
    """Capitalise the first letter of every word.

    Digits are untouched, so 'Gorakhpur 2' and a pincode survive. An
    all-capitals value is lowered first, which is the point: 'BELSAND'
    becomes 'Belsand'.

    One known limit: a genuine acronym inside one of these fields would be
    lowered too — a branch called 'IIT Nagar' would print as 'Iit Nagar'.
    No value in use does that today, and the alternative is a guess about
    which capitals were deliberate.
    """
    if not text:
        return text
    lowered = str(text).lower()
    return _WORD_START.sub(lambda m: m.group(1) + m.group(2).upper(), lowered)
