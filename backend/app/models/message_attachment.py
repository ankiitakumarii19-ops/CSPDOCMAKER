"""
CSP DocMaker — a photo, video or file a person attaches to a message (No. 257)

Messaging → Ask CSPs: the person attaches one file, it is kept here, and
every part of the send (the screen sends 25 CSPs per request) uses the same
row. Kept in the database like every other file the app holds (D5), scoped
by workspace_id (workspace_context), so one organisation never reads
another's.

platform_ref is the WhatsApp platform's handle for the file
("wamedia://..."), so it is uploaded to the platform once, not once per CSP.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

IMAGE = "image"
VIDEO = "video"
DOCUMENT = "document"
MEDIA_KINDS = (IMAGE, VIDEO, DOCUMENT)


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    media_kind: Mapped[str] = mapped_column(String(20), nullable=False,
                                            comment="image | video | document")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False,
                                          comment="SHA-256 of data")
    uploaded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform_ref: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="WhatsApp platform's handle, once uploaded there")
    platform_ref_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
