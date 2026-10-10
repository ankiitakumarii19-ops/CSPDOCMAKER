"""
CSP DocMaker — Document Job Model

Tracks individual document generation within a processing job.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Enum as SAEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.enums import DocumentType, ValidationStatus


class DocumentJob(Base):
    __tablename__ = "document_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    processing_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_jobs.id"), nullable=False, index=True
    )
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, name="document_type", native_enum=False,
               create_constraint=False, length=50), nullable=False
    )
    template_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="v1.0",
        comment="Version of the template used for generation"
    )
    generated_file_reference: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        comment="Internal path/reference to the generated DOCX file"
    )
    validation_status: Mapped[ValidationStatus] = mapped_column(
        SAEnum(ValidationStatus, name="validation_status", create_type=False),
        nullable=False,
        default=ValidationStatus.PASSED,  # Default pending, updated after validation
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    processing_job = relationship("ProcessingJob", back_populates="document_jobs")

    def __repr__(self) -> str:
        return f"<DocumentJob {self.document_type.value} validation={self.validation_status.value}>"
