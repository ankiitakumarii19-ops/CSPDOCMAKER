"""
CSP DocMaker — the feedback loops (No. 150)

  * QualitySuggestion — loop 1: the same correction to an INFO-filled value
    seen on several CSPs ("INFO gives AO NASHIK by branch VISARWADI; 3
    people changed it to AO DHULE") becomes a suggestion to fix INFO. An
    Admin accepts it (the team fixes the INFO sheet) or dismisses it; once
    INFO gives the corrected value the app marks it fixed. Suggest only —
    nothing is written to INFO by the app.
  * ContactFix — loop 2: a WhatsApp that did not reach the phone, or an
    email that bounced, for one CSP and one bad number / address. The CSP is
    asked for the right one through the other channel, once; when it is
    corrected, what failed is sent again.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class QualitySuggestion(Base):
    __tablename__ = "quality_suggestions"
    __table_args__ = (UniqueConstraint(
        "workspace_id", "field", "rule", "from_value", "to_value",
        name="uq_quality_suggestion"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    rule: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="The INFO match that gave the value, e.g. 'INFO AO block, by branch ...'")
    from_value: Mapped[str] = mapped_column(Text, nullable=False)
    to_value: Mapped[str] = mapped_column(Text, nullable=False)
    csp_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open",
        comment="open, accepted, fixed or dismissed")
    decided_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    fixed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)


class ContactFix(Base):
    __tablename__ = "contact_fixes"
    __table_args__ = (UniqueConstraint(
        "workspace_id", "csp_id", "problem", "bad_value",
        name="uq_contact_fix"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    csp_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    problem: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="whatsapp_undelivered or email_bounced")
    bad_value: Mapped[str] = mapped_column(String(320), nullable=False)
    failed_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="",
        comment="What did not arrive: documents, documents_ready, data_request…")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open",
        comment="open, asked, corrected, resent, done or stopped")
    asked_via: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    asked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    tries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    corrected_value: Mapped[Optional[str]] = mapped_column(String(320),
                                                           nullable=True)
    resent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)
