"""
CSP DocMaker — where an automatically filled value came from (No. 146)

The app fills blanks in a CSP's details by itself: INFO's org chart in the
sheet sync, the Zoho Lead's typed fields, the temporary Address tab. Each
such value is a guess somebody may later correct. These two tables keep
the guess and what people did with it, so the rules can be measured and
improved instead of trusted.

  * FieldProvenance — one row per CSP and filled field: where the value
    came from and why (`detail`, shown on the CSP's panel), what was filled
    (`auto_value`), what is there now, and whether a person has looked at
    it: auto (nobody yet), confirmed (kept it), corrected (changed it), or
    withdrawn (the source stopped supplying it and nobody had filled it).
  * FieldCorrection — append-only: every time a person changed one of
    those values, from what to what, how (the CSP's form, the app's sheet
    editor, the Google Sheet itself) and the edit distance from the
    original guess.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class FieldProvenance(Base):
    __tablename__ = "field_provenance"
    __table_args__ = (UniqueConstraint("workspace_id", "csp_id", "field",
                                       name="uq_field_provenance"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    csp_id: Mapped[str] = mapped_column(String(100), nullable=False,
                                        index=True)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="info, zoho or address_tab")
    detail: Mapped[str] = mapped_column(
        String(500), nullable=False, default="",
        comment="Why this value, in words: 'INFO AO block, by branch ...'")
    auto_value: Mapped[str] = mapped_column(Text, nullable=False)
    current_value: Mapped[str] = mapped_column(Text, nullable=False,
                                               default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="auto",
        comment="auto, confirmed, corrected or withdrawn")
    edit_distance: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="Levenshtein distance auto_value -> current_value once corrected")
    checked_via: Mapped[Optional[str]] = mapped_column(String(30),
                                                       nullable=True)
    checked_by: Mapped[Optional[str]] = mapped_column(String(255),
                                                      nullable=True)
    checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return (f"<FieldProvenance {self.csp_id}.{self.field} "
                f"{self.source} {self.status}>")


class FieldCorrection(Base):
    __tablename__ = "field_corrections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    csp_id: Mapped[str] = mapped_column(String(100), nullable=False,
                                        index=True)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    auto_value: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    edit_distance: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Levenshtein distance auto_value -> new_value")
    changed_via: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="csp_form, sheet_editor or sheet")
    changed_by: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="The signed-in person, 'CSP' for the form, NULL when unknown")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        index=True)

    def __repr__(self) -> str:
        return (f"<FieldCorrection {self.csp_id}.{self.field} "
                f"via {self.changed_via} d={self.edit_distance}>")
