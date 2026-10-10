"""
CSP DocMaker — Validation Result Model

Stores the outcome of each validation step (deterministic and AI-assisted).
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Enum as SAEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.enums import ValidationType, ValidationStatus


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    processing_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_jobs.id"), nullable=False, index=True
    )
    validation_type: Mapped[ValidationType] = mapped_column(
        SAEnum(ValidationType, name="validation_type"), nullable=False
    )
    status: Mapped[ValidationStatus] = mapped_column(
        SAEnum(ValidationStatus, name="validation_status", create_type=False),
        nullable=False,
    )
    issues: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="Structured list of validation issues found"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    processing_job = relationship("ProcessingJob", back_populates="validation_results")

    def __repr__(self) -> str:
        return f"<ValidationResult type={self.validation_type.value} status={self.status.value}>"
