"""
CSP DocMaker — who has which feature, and a workspace's own roles
(PROJECT-REGISTER No. 206, Stage 2)

access_roles     a workspace's own roles: a name, built on RM or Admin, and
                 which CSPs it may act on (own = its own and unowned ones,
                 as RMs today; all = every CSP). Rows keyed "rm" / "admin"
                 change only the built-in role's CSPs.
feature_access   one feature given (allowed) or taken away (not allowed) for
                 one subject: "role:<key>" or "person:<email>". No row =
                 today's access (services/feature_catalog.py).

The rules: services/feature_access.py. History: workspace_setting_changes
(keys "access:…", "role:…", "member_role:…").
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class AccessRole(Base):
    __tablename__ = "access_roles"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True, default=default_workspace_id)
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_role: Mapped[str] = mapped_column(String(20), nullable=False)
    record_scope: Mapped[str] = mapped_column(String(10), nullable=False,
                                              default="own")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)


class FeatureAccess(Base):
    __tablename__ = "feature_access"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True, default=default_workspace_id)
    feature: Mapped[str] = mapped_column(String(60), primary_key=True)
    subject: Mapped[str] = mapped_column(String(300), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)
