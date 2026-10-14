"""
CSP DocMaker — who is asked for a missing field

Every field a document needs belongs to someone who is in a position to know
it. Chasing the wrong person wastes everybody's time: an RM cannot tell you a
CSP's gender, and a CSP has never heard of their RBO.

Two owners, confirmed:

  CSP   — the CSP's own identity and whereabouts. Only they can supply these,
          so a blank one is chased with the CSP directly.
  ORG   — the bank and Eko hierarchy around them. Filled from INFO first;
          only what INFO cannot answer is asked of the CSP.

The order of resort for an ORG field is fixed:

  1. The INFO tab, which states who covers which territory. AO and RBO are
     answered here too once those columns are added to INFO.
  2. The CSP, on WhatsApp — for whatever INFO still could not fill.

  Changed 11 Oct 2026 (tracker No. 53): an RM is never asked for anything.
  Their job is to search a CSP and choose documents; every missing detail
  goes to the CSP, and the answer is written to the sheet.

Nothing here decides whether a document can be generated; that stays derived
from the templates. This decides only who is asked.
"""

import logging
import os
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

CSP = "csp"
ORG = "org"

# ---- the CSP's own details --------------------------------------------
# Keys are CSPRecord attribute names, so there is no third vocabulary to
# keep in step. Order is the order a person is asked for them.
CSP_OWNED: Tuple[str, ...] = (
    "csp_code",
    "name",
    "mobile",
    "email",
    "gender",
    "address",
    "district",
    "state",
    # A CSP knows which branch they are attached to and its code — it is on
    # their own paperwork. Asking an RM to look those up for every CSP was
    # chasing the wrong person for something the CSP can answer at once.
    "branch_name",
    "branch_code",
    "photo_url",
)

# ---- the hierarchy around the CSP --------------------------------------
# branch_contact and rbo_contact are deliberately absent. No template
# prints either, and nothing can: neither is in FIELD_TO_CSP_ATTR, so a
# document could not carry them even if a placeholder asked for one. They
# are still columns on the record and still synced from the sheet — they
# are simply never chased, because chasing somebody for a value no
# document can use is pure cost.
ORG_OWNED: Tuple[str, ...] = (
    "ao",
    "dc",
    "dc_email",
    "dc_contact",
    "lho",
    "rm_name",
    "asm_name",
    "asm_email",
    "asm_contact",
    "rbo_name",
)

# Which ORG fields the INFO tab can answer without troubling anyone.
# Measured against the live sheet, not assumed:
#   * dc/dc_email/dc_contact  — the district uniquely picks one DC row.
#   * asm_*                   — LHO + State picks one ASM.
#   * rm_name                 — LHO + State picks one RM.
#   * lho/state               — every one of the 79 districts in the DC block
#                               belongs to exactly one DC, and that row names
#                               both, so the district implies them.
# ao and rbo_name are bank facts. The INFO tab is Eko's own org chart and
# holds no column for either, so they are always asked for.
INFO_CAN_FILL: Tuple[str, ...] = (
    "dc", "dc_email", "dc_contact",
    "asm_name", "asm_email", "asm_contact",
    "rm_name",
    "lho", "state",
)

ALWAYS_MANUAL: Tuple[str, ...] = tuple(
    f for f in ORG_OWNED if f not in INFO_CAN_FILL
)

# What a field is called when a human is asked for it.
LABELS: Dict[str, str] = {
    "csp_code": "CSP Code",
    "name": "CSP Name",
    "mobile": "CSP Mobile Number",
    "email": "CSP Email Id",
    "gender": "Gender",
    "address": "Address",
    "district": "District",
    "state": "State",
    "photo_url": "Photograph",
    "branch_name": "Branch Name",
    "branch_code": "Branch Code",
    "branch_contact": "Branch Contact Number",
    "ao": "AO",
    "dc": "DC",
    "dc_email": "DC Email Id",
    "dc_contact": "DC Contact Number",
    "lho": "LHO",
    "rm_name": "Relationship Manager (RM)",
    "asm_name": "ASM",
    "asm_email": "ASM Email Id",
    "asm_contact": "ASM Contact Number",
    "rbo_name": "RBO Name",
    "rbo_contact": "RBO Contact No.",
    "has_id_card": "Do you have a CSP ID Card?",
    "has_csp_certificate": "Do you have a CSP Certificate?",
    "has_training_certificate": "Do you have a Training Certificate?",
    "has_bcp": "Do you have a Business Continuity Plan (BCP)?",
}

# The same labels in Hindi. A CSP's form shows both, in the wording the
# supplied Google Form used, so the two surfaces read identically to anyone
# who sees them side by side. Only the fields a CSP is ever shown need one;
# the hierarchy fields are put to an RM, who works in English.
LABELS_HI: Dict[str, str] = {
    "csp_code": "CSP कोड",
    "name": "CSP का नाम",
    "mobile": "मोबाइल नंबर",
    "email": "ईमेल आईडी",
    "gender": "जेंडर",
    "address": "पता",
    "district": "जिला",
    "state": "राज्य",
    "photo_url": "फोटो",
    "branch_name": "शाखा का नाम",
    "branch_code": "शाखा कोड",
    "has_id_card": "क्या आपके पास CSP आईडी कार्ड है?",
    "has_csp_certificate": "क्या आपके पास CSP प्रमाणपत्र है?",
    "has_training_certificate": "क्या आपके पास प्रशिक्षण प्रमाणपत्र है?",
    "has_bcp": "क्या आपके पास बिजनेस निरंतरता योजना (BCP) है?",
    # The hierarchy fields, now that a CSP may be asked for them.
    "ao": "AO (प्रशासनिक कार्यालय)",
    "rbo_name": "RBO का नाम",
    "dc": "DC का नाम",
    "dc_email": "DC की ईमेल आईडी",
    "dc_contact": "DC का मोबाइल नंबर",
    "lho": "LHO",
    "rm_name": "RM का नाम",
    "asm_name": "ASM का नाम",
    "asm_email": "ASM की ईमेल आईडी",
    "asm_contact": "ASM का मोबाइल नंबर",
}

# What an upload button says, when the answer was Yes.
UPLOAD_LABELS: Dict[str, tuple] = {
    "has_id_card": ("Upload CSP ID Card",
                    "CSP आईडी कार्ड अपलोड करें"),
    "has_csp_certificate": ("Upload CSP Certificate",
                            "CSP प्रमाणपत्र अपलोड करें"),
    "has_training_certificate": ("Upload Training Certificate",
                                 "प्रशिक्षण प्रमाणपत्र अपलोड करें"),
    "has_bcp": ("Upload Business Continuity Plan (BCP)",
                "बिजनेस निरंतरता योजना (BCP) अपलोड करें"),
}

# Choices that are themselves shown in both languages.
GENDER_CHOICES = (
    ("Male", "Male / पुरुष"),
    ("Female", "Female / महिला"),
)
YESNO_CHOICES = (
    ("No", "No / नहीं"),
    ("Yes", "Yes / हाँ"),
)


def label_bilingual(field: str) -> str:
    """'CSP Name / CSP ka naam' — both languages, as the form shows it."""
    english = LABELS.get(field, field)
    hindi = LABELS_HI.get(field)
    return f"{english} / {hindi}" if hindi else english


# How the field is entered, for whichever form is put in front of someone.
INPUT_TYPES: Dict[str, str] = {
    "mobile": "phone", "email": "email", "address": "address",
    "gender": "gender", "photo_url": "photo",
    "dc_email": "email", "asm_email": "email",
    "dc_contact": "phone", "asm_contact": "phone",
    "branch_contact": "phone", "rbo_contact": "phone",
    # Yes/No, and an upload that only appears on Yes.
    "has_id_card": "yesno_upload",
    "has_csp_certificate": "yesno_upload",
    "has_training_certificate": "yesno_upload",
    "has_bcp": "yesno_upload",
}

# ---- which documents the CSP already holds ------------------------------
# Not missing data: no document needs these, and a blank one blocks nothing.
# They are asked so the system does not re-issue a document the CSP already
# has. Kept apart from CSP_OWNED so they can never leak into the required
# fields a document is generated from.
DOCUMENTS_HELD: Tuple[str, ...] = (
    "has_id_card",
    "has_csp_certificate",
    "has_training_certificate",
    "has_bcp",
)

# The document each question is about, named plainly. "Do you have a CSP ID
# Card?" is the right wording on a form and the wrong wording in the first
# column of a table of Yes/No counts.
HELD_DOCUMENT_NAMES: Dict[str, str] = {
    "has_id_card": "CSP ID Card",
    "has_csp_certificate": "CSP Certificate",
    "has_training_certificate": "Training Certificate",
    "has_bcp": "Business Continuity Plan (BCP)",
}


def held_document_name(field: str) -> str:
    return HELD_DOCUMENT_NAMES.get(field, label_of(field))

# What the CSP may change on their own form.
#
# csp_code is deliberately absent. It identifies the record, and the link
# already says which CSP this is — so letting it be edited could only either
# do nothing (confusing) or point the submission at a different CSP. It is
# shown on the form, read-only, so the person can see which record they are
# confirming.
CSP_EDITABLE: Tuple[str, ...] = tuple(f for f in CSP_OWNED if f != "csp_code")

ALL_FIELDS: Tuple[str, ...] = CSP_OWNED + ORG_OWNED + DOCUMENTS_HELD


def owner_of(field: str) -> str:
    """CSP or ORG. Raises for a field nobody has been made responsible for."""
    if field in CSP_OWNED or field in DOCUMENTS_HELD:
        return CSP
    if field in ORG_OWNED:
        return ORG
    raise KeyError(
        f"{field!r} has no owner. Add it to CSP_OWNED or ORG_OWNED — a field "
        f"with no owner can never be chased, so it would block silently."
    )


def label_of(field: str) -> str:
    return LABELS.get(field, field)


def input_type_of(field: str) -> str:
    return INPUT_TYPES.get(field, "text")


def _is_blank(record, field: str) -> bool:
    if field == "photo_url":
        # A path whose file is gone is no photo (No. 99): ask for one.
        from app.services import csp_photo_store
        if not getattr(record, "csp_id", None):
            photo = (getattr(record, "photo_url", None) or "").strip()
            return not (photo and os.path.isfile(photo))
        return csp_photo_store.original_path(record) is None
    value = getattr(record, field, None)
    return not (str(value).strip() if value is not None else "")


def missing(record) -> Dict[str, List[str]]:
    """Split what this CSP is still missing by who will be asked.

    Returns {"csp": [...], "org": [...]} in the declared order, so the
    question a person is asked comes out in a predictable sequence.
    """
    return {
        CSP: [f for f in CSP_OWNED if _is_blank(record, f)],
        ORG: [f for f in ORG_OWNED if _is_blank(record, f)],
    }


def form_fields() -> List[str]:
    """Everything the CSP's own form puts in front of them.

    Confirmed behaviour: the form shows all of it, pre-filled with whatever
    is already known, and the CSP corrects what is wrong — rather than
    showing only the blanks. They are verifying their record, not filling a
    gap, so a wrong value already on file gets a chance to be fixed.
    """
    return list(CSP_EDITABLE) + list(DOCUMENTS_HELD)


def request_fields(record) -> List[str]:
    """Everything a CSP's link asks: their own details (all of them, for
    checking), what they already hold, and any ORG detail INFO could not
    fill. INFO is applied on every sync, so an ORG field still blank on the
    record is one INFO could not answer."""
    return form_fields() + [f for f in ORG_OWNED if _is_blank(record, f)]


def unfillable_by_info(fields) -> List[str]:
    """Of these, the ones INFO could never answer — a human must supply them.

    Used to avoid raising an alert for something the next INFO pass will fill
    by itself.
    """
    return [f for f in fields if f not in INFO_CAN_FILL]
