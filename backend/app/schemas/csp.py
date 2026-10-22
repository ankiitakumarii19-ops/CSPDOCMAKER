"""
CSP DocMaker — CSP Schemas

Pydantic models for CSP search, detail, and update.

These mirror the real csp_records columns. Fields that were dropped when the
schema moved to the supplied CSP sheet (module_name, email_id, onboarded_date,
onboarding_month, onboarding_year, status) are gone from here too: exposing
them returned permanent nulls, and accepting them let an update report success
while saving nothing.
"""

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class CSPDetailResponse(BaseModel):
    """CSP record detail — returned in search results and selection."""
    csp_id: str
    csp_code: Optional[str] = None
    name: str
    email: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    branch_name: Optional[str] = None
    branch_code: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    ao: Optional[str] = None
    lho: Optional[str] = None
    dc: Optional[str] = None
    dc_email: Optional[str] = None
    dc_contact: Optional[str] = None
    rbo_name: Optional[str] = None
    asm_name: Optional[str] = None
    asm_email: Optional[str] = None
    asm_contact: Optional[str] = None
    photo_url: Optional[str] = None

    # Owned by the application, not by the sheet.
    certificate_date: Optional[date] = None
    origin: Optional[str] = None
    rm_name: Optional[str] = None
    rm_email: Optional[str] = None
    rm_resolution: Optional[str] = None
    # Why nothing may be sent to this CSP now (No. 121), or None.
    send_hold: Optional[str] = None

    model_config = {"from_attributes": True}


class CSPSearchResponse(BaseModel):
    """CSP search results."""
    results: List[CSPDetailResponse]
    total: int
    query: str


class CSPUpdateRequest(BaseModel):
    """Values an RM supplies to fill in a CSP's missing data.

    Only fields a person can actually correct are here. Anything not listed is
    rejected outright rather than ignored, so an RM is never shown a success
    message for a value that was silently discarded.
    """
    csp_code: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    branch_name: Optional[str] = None
    branch_code: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    ao: Optional[str] = None
    lho: Optional[str] = None
    dc: Optional[str] = None
    dc_email: Optional[str] = None
    dc_contact: Optional[str] = None
    rbo_name: Optional[str] = None
    asm_name: Optional[str] = None
    asm_email: Optional[str] = None
    asm_contact: Optional[str] = None

    # The date an old CSP's certificates are made. The RM supplies it once and
    # it is kept on the record so both certificates reuse the same date.
    certificate_date: Optional[date] = Field(
        default=None,
        description="Date the certificate is made (YYYY-MM-DD). Printed as "
                    "DD.MM.YYYY on the Training Certificate and as "
                    "'Month YYYY' on the BCP.",
    )

    model_config = {"extra": "forbid"}
