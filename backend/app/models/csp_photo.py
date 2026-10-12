"""
CSP DocMaker — CSP photos, stored in the database

Decided 12 Oct 2026 (tracker No. 47 / No. 89): the photo is part of a CSP's
complete record, so the image itself is kept here, not only a path on disk.

Two kinds per CSP, one row each (replaced when the photo changes):

  * original  — the photo as obtained (taken from the Zoho KYC pack, or
                uploaded by an RM);
  * passport  — the white-background 35 x 45 mm version printed on the
                documents.

The files on disk remain the working copies the document pipeline reads;
this table is the permanent record.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, ForeignKeyConstraint, Integer, LargeBinary, String,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

ORIGINAL = "original"
PASSPORT = "passport"
KINDS = (ORIGINAL, PASSPORT)


class CSPPhoto(Base):
    __tablename__ = "csp_photos"
    __table_args__ = (
        UniqueConstraint("workspace_id", "csp_id", "kind",
                         name="uq_csp_photos_workspace_csp_kind"),
        # A CSP code is unique within a workspace, so the link is both.
        ForeignKeyConstraint(
            ["workspace_id", "csp_id"],
            ["csp_records.workspace_id", "csp_records.csp_id"],
            name="csp_photos_csp_fkey", ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
        default=default_workspace_id,
    )
    csp_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="original | passport")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_data: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, comment="The image itself (bytea)")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256 of file_data")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)
