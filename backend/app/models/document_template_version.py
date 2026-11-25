"""
CSP DocMaker — earlier versions of a document template (No. 240, Stage 5)

Before a template's file, wording or mapping is replaced (new upload, wording
edit, restore), what it was is kept here, so an earlier version can be looked
at, downloaded and put back. Documents are still made only from the live
template (document_templates); nothing here is read by generation.

Scoped by workspace_id like every organisation-owned row.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class DocumentTemplateVersion(Base):
    __tablename__ = "document_template_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    template_code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    placeholder_map: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    photo_marker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    was_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    reason: Mapped[str] = mapped_column(String(60), nullable=False,
                                        comment="new_upload | wording_edit | restore")
    saved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
