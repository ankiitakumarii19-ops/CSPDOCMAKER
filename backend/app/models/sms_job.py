"""
CSP DocMaker — SMS Job Model

Tracks SMS notification delivery to CSPs after successful email delivery.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Enum as SAEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.enums import SMSStatus


class SMSJob(Base):
    __tablename__ = "sms_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    processing_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_jobs.id"), nullable=False, index=True
    )
    recipient: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="CSP mobile from trusted CSP record"
    )
    message_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="Message ID from SMS provider response"
    )
    status: Mapped[SMSStatus] = mapped_column(
        SAEnum(SMSStatus, name="sms_status"), nullable=False, default=SMSStatus.PENDING
    )
    failure_reason: Mapped[str | None] = mapped_column(
        String(2000), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    processing_job = relationship("ProcessingJob", back_populates="sms_jobs")

    def __repr__(self) -> str:
        return f"<SMSJob to={self.recipient} status={self.status.value}>"
