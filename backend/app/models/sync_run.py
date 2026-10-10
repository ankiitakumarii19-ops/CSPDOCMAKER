"""
CSP DocMaker — Sync Run Model

One row per synchronisation attempt (CSP sheet or authorization sheet).

This is what makes "has the system ever synced?" answerable, which the CSP
sync needs in order to tell a first-run baseline (every row already there, so
nothing is a new CSP) from a later run (a row that appears is a new CSP).
It also gives the admin dashboard a real "last successful sync" value.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class SyncRun(Base):
    __tablename__ = "sync_runs"

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
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="Which sheet was synced: 'csp' or 'authorization'"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="running, completed or failed"
    )
    is_baseline: Mapped[bool] = mapped_column(
        default=False, nullable=False,
        comment="True for the first successful CSP sync — its rows are existing CSPs"
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="Why the run failed. The next run retries; RMs are never shown this."
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<SyncRun {self.source} {self.status} rows={self.rows_read}>"
