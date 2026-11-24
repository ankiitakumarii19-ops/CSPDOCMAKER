"""
CSP DocMaker — a workspace's own settings and their history
(PROJECT-REGISTER No. 204, Stage 1: Settings centre)

workspace_settings          one row per setting a workspace has changed;
                            no row = the server's value (Eko's value today).
workspace_setting_changes   every change, with the value before and after,
                            who, how (screen / chat / undo / back to the
                            standard value) and when. Never switched off;
                            the screen's Undo works from it.

Which settings exist and their safe ranges: services/settings_catalog.py.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class WorkspaceSetting(Base):
    __tablename__ = "workspace_settings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True, default=default_workspace_id)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)


class WorkspaceSettingChange(Base):
    __tablename__ = "workspace_setting_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True,
                                    autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # None = the standard (server / Eko) value was in force.
    old_value: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    via: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="screen | chat | undo | standard")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        index=True)


class WorkspaceSecret(Base):
    """A workspace's password or key (No. 210), encrypted by
    services/secret_store.py. Never sent to a screen or a log."""
    __tablename__ = "workspace_secrets"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True, default=default_workspace_id)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)
