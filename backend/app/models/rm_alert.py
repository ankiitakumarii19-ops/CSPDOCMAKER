"""
CSP DocMaker — RM Alert

What a Relationship Manager is asked to fix. Until this existed, "alert the
RM" meant a line in a log file that nobody reads, so a CSP could sit blocked
indefinitely with no one told.

One open alert per CSP per kind. The worker re-runs every few minutes, so it
updates the existing alert rather than filing a new one each time — otherwise
an RM would wake up to hundreds of duplicates for a single CSP.

Alerts resolve themselves: once the data arrives the next run generates the
documents and closes the alert. An RM never has to tick anything off.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

# What the RM is being asked for.
MISSING_DATA = "missing_data"
PHOTO_MISSING = "photo_missing"

OPEN = "open"
RESOLVED = "resolved"


class RMAlert(Base):
    __tablename__ = "rm_alerts"

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
        String(100),
        ForeignKey("csp_records.csp_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Null when the CSP is unresolved: every RM then sees it, matching the
    # rule that an unowned CSP is never stranded.
    rm_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True,
        comment="The RM asked to act; NULL means every RM is asked",
    )
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="missing_data | photo_missing",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OPEN, index=True,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # The exact fields still needed, so the UI can build the form from this
    # alone rather than recomputing it.
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # At most one open alert of a kind per CSP. A partial index would be
        # tidier, but this keeps the constraint plain: resolved rows carry
        # their resolution time, so they no longer collide.
        UniqueConstraint("csp_id", "kind", "status", "resolved_at",
                         name="uq_rm_alert_open_per_csp_kind"),
        Index("ix_rm_alerts_owner_status", "rm_email", "status"),
    )

    def __repr__(self) -> str:
        return f"<RMAlert {self.csp_id} {self.kind} {self.status}>"
