"""
CSP DocMaker — dashboards a Super Admin builds

A dashboard is a named set of widgets. One is permanent: Document
Operations, which reports on what the system exists to do. The rest are
built, rearranged and retired as a workspace's needs change — the CSP
verification dashboard, for instance, matters while data is being collected
and stops mattering once it is.

Retiring a dashboard hides the screen. It never deletes what the screen was
showing: the submissions, tokens and history stay, so switching it back on
brings the whole record with it, and the audit trail of who changed what on
a CSP's record survives either way.

A widget cannot show whatever it likes. It names a metric from the registry
in `metric_registry.py`, and a dashboard that asks for a metric nobody can
compute is refused at the point of saving rather than rendering an error
later.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.workspace_context import default_workspace_id

# The dashboard that cannot be removed. It reports on document issuing,
# which is the thing this system is for.
SYSTEM_SLUG = "document-operations"

# What a widget can be.
METRIC_CARD = "metric_card"     # one number, optionally clickable
TABLE = "table"                 # rows, with columns chosen from the metric
BREAKDOWN = "breakdown"         # one metric split by a dimension

WIDGET_KINDS = (METRIC_CARD, TABLE, BREAKDOWN)


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
        default=default_workspace_id,
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str] = mapped_column(
        String(60), nullable=False, default="fa-chart-line",
    )

    # A system dashboard cannot be deleted or deactivated. There is exactly
    # one, and without it the system has no screen for the work it does.
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    # Hidden rather than deleted. The data behind it is untouched.
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    widgets: Mapped[list["DashboardWidget"]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="DashboardWidget.position",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_dashboard_slug"),
    )

    def __repr__(self) -> str:
        return f"<Dashboard {self.slug}{' (system)' if self.is_system else ''}>"


class DashboardWidget(Base):
    __tablename__ = "dashboard_widgets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dashboards.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="metric_card | table | breakdown",
    )
    # The metric this widget shows, from metric_registry. Validated on save.
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    # Anything the widget needs beyond its metric: which columns a table
    # shows, what a card links to, how a breakdown is split.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Columns spanned on a 4-wide grid",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dashboard: Mapped["Dashboard"] = relationship(back_populates="widgets")

    def __repr__(self) -> str:
        return f"<DashboardWidget {self.kind}:{self.metric}>"
