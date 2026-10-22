"""
CSP DocMaker — what the Calling and Lead raw data sheets last said (No. 121)

One row per CSP code seen in either sheet, in the Eko workspace. It is the
app's memory between runs: the Lead raw data sheet only says what a CSP's
stage is NOW, so noticing the moment it changes to "Go Live Done" needs the
previous answer kept somewhere.

  * baseline_live — the CSP was already live when this started (21 Oct
                    2026: "treat as already done") — never mailed as new.
  * went_live_at  — when the app saw it change to live after that.
  * imported_as   — copied into CSPDATA as "baseline" (old) or "new"; the
                    sheet sync reads this when it creates the CSP's record,
                    so an old CSP added to KOData is never mailed as new.
  * hold_reason   — why nothing may be sent to this CSP right now, or None.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (Boolean, DateTime, ForeignKey, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class SourceSheetState(Base):
    __tablename__ = "source_sheet_states"
    __table_args__ = (UniqueConstraint("workspace_id", "csp_code",
                                       name="uq_source_sheet_state_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    csp_code: Mapped[str] = mapped_column(String(50), nullable=False)

    in_calling: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                             default=False)
    calling_status: Mapped[Optional[str]] = mapped_column(String(100),
                                                          nullable=True)
    in_lead: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                          default=False)
    lead_remarks: Mapped[Optional[str]] = mapped_column(String(300),
                                                        nullable=True)
    lead_live: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=False)
    baseline_live: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                default=False)
    went_live_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)

    imported_as: Mapped[Optional[str]] = mapped_column(String(20),
                                                       nullable=True)
    imported_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    # Which KOData columns were filled from Zoho, and from which Lead.
    zoho_filled: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    hold_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)
