"""
CSP DocMaker — a workspace's own files (No. 240, SaaS upgrade Stage 3)

Today: the organisation's logo (kind "logo"). One row per workspace and kind.
Kept in the database like every other file the app holds (D5). Scoped by
workspace_id like every other organisation-owned row (workspace_context), so
one organisation never reads another's.

No row = the app's own eko KIOSK logo, exactly as before.
"""

import uuid
from datetime import datetime

from sqlalchemy import (DateTime, ForeignKey, Integer, LargeBinary, String,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class WorkspaceFile(Base):
    __tablename__ = "workspace_files"
    __table_args__ = (UniqueConstraint("workspace_id", "kind",
                                       name="uq_workspace_files_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    kind: Mapped[str] = mapped_column(String(30), nullable=False,
                                      comment="logo")
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str] = mapped_column(String(60), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False,
                                          comment="SHA-256; also its version")
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)
