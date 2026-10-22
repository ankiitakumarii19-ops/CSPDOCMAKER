"""
CSP DocMaker — CSP Record Model

Stores CSP information synchronized from the source Google Sheet.
This is the trusted CSP data used for document generation and email delivery.
"""

import uuid
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.workspace_context import default_workspace_id


class CSPRecord(Base):
    __tablename__ = "csp_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Which customer this belongs to. NOT NULL everywhere: a row owned by
    # nobody is a row that leaks into whoever queries without a filter.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
        default=default_workspace_id,
    )
    csp_id: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
        comment="Business key — the sheet's 'CSP Code' (the sheet has no separate ID)"
    )
    csp_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="CSP Code used in documents — may differ from csp_id"
    )
    name: Mapped[str] = mapped_column(
        String(500), nullable=False
    )
    email: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="CSP registered email — used as the trusted recipient"
    )
    mobile: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="CSP registered mobile — used for SMS notification"
    )
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The CSP's own details. Nobody but the CSP can supply these, so a blank
    # one is chased with the CSP directly rather than with their RM.
    gender: Mapped[str | None] = mapped_column(String(50), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Branch name for ID Card, Training Certificate, BCP"
    )
    branch_code: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Branch code for ID Card, Training Certificate, BCP"
    )
    branch_contact: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Branch Contact Number — a bank fact; the INFO tab cannot supply it"
    )
    photo_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="Path/URL to CSP photo — required for CSP ID Card"
    )
    rbo_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="RBO name for BCP document"
    )
    rbo_contact: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="RBO Contact No. — a bank fact; the INFO tab cannot supply it"
    )
    # Organisational hierarchy (sheet columns) — used for RM resolution and
    # admin dashboard filters. 'AO' also fills the BCP "Module Name" field.
    district: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ao: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="AO — also the value printed as 'Module' on the BCP"
    )
    lho: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="LHO — resolves the RM when the RM cell is empty"
    )
    dc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dc_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dc_contact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rm_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True,
        comment="Relationship Manager name from the sheet — matched to users.name"
    )
    # Filled from the INFO tab by LHO + State, like dc and asm_name. No
    # document prints a circle head; it exists so admins can filter by one.
    circle_head: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Circle Head covering this CSP's LHO/State, from the INFO tab",
    )
    asm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asm_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asm_contact: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ---- which documents the CSP already holds -------------------------
    # Answered by the CSP themselves, so the system does not re-issue a
    # document someone already has. Stored as the sheet stores it ("Yes" /
    # "No" / blank) rather than as a boolean: the sync compares every field
    # against its cell as text, and a bool would never match.
    # Blank means nobody has asked yet, which is not the same as "No".
    has_id_card: Mapped[str | None] = mapped_column(String(10), nullable=True)
    has_csp_certificate: Mapped[str | None] = mapped_column(
        String(10), nullable=True)
    has_training_certificate: Mapped[str | None] = mapped_column(
        String(10), nullable=True)
    has_bcp: Mapped[str | None] = mapped_column(String(10), nullable=True)

    certificate_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        comment=(
            "Date printed on the certificates. Set automatically for a new CSP; "
            "entered by the RM for an existing CSP and reused afterwards."
        ),
    )
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Why nothing may be sent to this CSP now (No. 121): Inactive in the
    # Calling sheet, or not yet "Go Live Done" in the Lead raw data sheet.
    # Set by the source-sheets job; every sending path checks it.
    send_hold: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Sync / workflow bookkeeping ----
    origin: Mapped[str] = mapped_column(
        String(20), nullable=False, default="baseline", index=True,
        comment=(
            "'baseline' = already in the sheet at the first sync (an existing "
            "CSP, never auto-processed); 'new' = appeared afterwards"
        ),
    )
    # An existing CSP their RM has put into the automatic pipeline.
    #
    # Baseline CSPs are deliberately excluded from automatic processing —
    # otherwise the first sync would email every CSP the organisation has.
    # That protection is against doing it in bulk by accident, not against
    # doing it on purpose, so an RM can enrol one and from then on it is
    # treated exactly like a new CSP: generated, validated and sent without
    # anybody doing it step by step.
    #
    # `origin` is left alone. It records whether this CSP predated the
    # system, which stays true however they are later processed.
    auto_enrolled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When an RM put this existing CSP into the automatic pipeline",
    )
    auto_enrolled_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )

    new_csp_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When the automated new-CSP workflow was started. Prevents duplicates.",
    )
    rm_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True,
        comment="Login email of the RM this CSP belongs to, resolved from rm_name/LHO",
    )
    rm_resolution: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unresolved", index=True,
        comment="How rm_email was decided: 'sheet', 'lho' or 'unresolved'",
    )

    source_row_identifier: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True,
        comment="Unique identifier for the source Google Sheet row to prevent duplicate imports"
    )
    source_last_updated: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<CSPRecord {self.csp_id} name={self.name}>"

