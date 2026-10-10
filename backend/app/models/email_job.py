"""
CSP DocMaker — Email Job Model

Tracks email delivery attempts and their outcomes.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Enum as SAEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.workspace_context import default_workspace_id
from app.models.enums import EmailStatus


class EmailJob(Base):
    __tablename__ = "email_jobs"

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
    processing_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_jobs.id"), nullable=False, index=True
    )
    recipient: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="CSP email from trusted CSP record — not user-supplied"
    )
    subject: Mapped[str] = mapped_column(
        String(500), nullable=False
    )
    provider_message_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Message ID from Gmail API response"
    )
    status: Mapped[EmailStatus] = mapped_column(
        SAEnum(EmailStatus, name="email_status"), nullable=False, default=EmailStatus.PENDING
    )
    failure_reason: Mapped[str | None] = mapped_column(
        String(2000), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Which documents this email carried. Needed for per-document
    # delivery counts: one email carries a whole job's documents.
    documents = relationship(
        "EmailDocument", back_populates="email_job",
        cascade="all, delete-orphan", lazy="selectin",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    processing_job = relationship("ProcessingJob", back_populates="email_jobs")

    def __repr__(self) -> str:
        return f"<EmailJob to={self.recipient} status={self.status.value}>"
