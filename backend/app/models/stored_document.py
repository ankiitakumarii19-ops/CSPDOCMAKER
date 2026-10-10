"""
CSP DocMaker — Stored Document Model

Permanent storage for generated documents, held in PostgreSQL rather than on
disk so the record survives redeploys and container restarts.

One row per file: a document generated in both formats produces two rows, one
DOCX and one PDF, sharing a csp_id, document_type and version. Regenerating a
document does not overwrite anything — it stores a new, higher version, so the
exact file a CSP was sent remains retrievable.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, Enum as SAEnum, ForeignKey, Index, Integer, LargeBinary,
    String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id
from app.models.enums import DocumentFormat, DocumentType


class StoredDocument(Base):
    __tablename__ = "stored_documents"

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
    processing_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="The job that produced this file, when it came from a workflow",
    )
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, name="document_type", native_enum=False,
               create_constraint=False, length=50),
        nullable=False,
    )
    file_format: Mapped[DocumentFormat] = mapped_column(
        SAEnum(DocumentFormat, name="document_format"),
        nullable=False,
        comment="docx (generated) or pdf (converted, this is what the CSP receives)",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Increments per csp_id + document_type; old versions are kept",
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_data: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, comment="The file itself (PostgreSQL bytea)"
    )
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Bytes, stored so size can be read without the blob"
    )
    checksum: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256 of file_data, for integrity checks"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # A given version of a document exists once per format.
        UniqueConstraint(
            "csp_id", "document_type", "file_format", "version",
            name="uq_stored_document_version",
        ),
        Index("ix_stored_documents_csp_type", "csp_id", "document_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<StoredDocument {self.csp_id} {self.document_type.value} "
            f"{self.file_format.value} v{self.version} ({self.file_size} bytes)>"
        )
