"""
CSP DocMaker — the platform above the workspaces (No. 240, SaaS upgrade Stage 6)

Kept by the Supreme Owner (SUPREME_OWNER_EMAILS), never by a workspace:

  * Plan                 — a subscription plan: limits (0 / NULL = none) and
                           an informational price. Nothing is charged: no
                           payment gateway is called (readiness only).
  * WorkspaceSubscription — which plan a workspace is on, its status, trial
                           end, white-label / custom domain, and the payment
                           provider's reference for later. No row = no plan
                           = no limits (every workspace today, so nothing
                           changes). Eko is put on "unlimited" by the
                           migration.
  * PlatformAnnouncement — a banner for every workspace, or one.

WorkspaceSubscription carries workspace_id, so inside a workspace it is
scoped like every organisation-owned row (a workspace reads only its own);
the console reads across with all_workspaces(). PlatformAnnouncement uses
`target_workspace_id` on purpose: NULL means "everyone" and must not be
filtered away by the workspace scoping.
"""

import uuid
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, Integer,
                        String, Text, func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

SUBSCRIPTION_STATUSES = ("trial", "active", "past_due", "cancelled", "unlimited")


class Plan(Base):
    __tablename__ = "plans"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Informational until a payment provider is connected.
    price_monthly_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    # 0 or NULL = no limit.
    max_documents_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_storage_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trial_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False)


class WorkspaceSubscription(Base):
    __tablename__ = "workspace_subscriptions"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True, default=default_workspace_id)
    plan_key: Mapped[str] = mapped_column(
        String(40), ForeignKey("plans.key"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active",
                                        comment="trial | active | past_due | cancelled | unlimited")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Payment-gateway readiness: filled in when a provider is connected.
    payment_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    payment_customer_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # White-labelling and own address, for later.
    white_label: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    custom_domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False)


class PlatformAnnouncement(Base):
    __tablename__ = "platform_announcements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NULL = every workspace.
    target_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True, index=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="info",
                                       comment="info | warning")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
