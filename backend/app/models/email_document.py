"""
CSP DocMaker — Which documents an email carried

One email carries all of a job's documents, so email_jobs alone cannot say
whether a particular document was delivered. Without this table the admin
dashboard's per-document "Sent" and "Failed (Send)" counts have no source:
they could only be reported per job.

A row per (email, document type) fixes that. The email's own status decides
whether each of its documents counts as sent or failed, so nothing here
duplicates state — the link is what was missing.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, Enum as SAEnum, ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import DocumentType


class EmailDocument(Base):
    __tablename__ = "email_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("email_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, name="document_type", native_enum=False,
               create_constraint=False, length=50),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    email_job = relationship("EmailJob", back_populates="documents")

    __table_args__ = (
        UniqueConstraint("email_job_id", "document_type",
                         name="uq_email_document"),
    )

    def __repr__(self) -> str:
        return f"<EmailDocument {self.document_type.value}>"
