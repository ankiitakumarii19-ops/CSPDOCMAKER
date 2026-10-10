"""
CSP DocMaker — Processing Job Model

Tracks the lifecycle of every CSP document processing operation.
Implements the workflow state machine from Section 29.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Enum as SAEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.workspace_context import default_workspace_id
from app.models.enums import WorkflowType, JobState


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

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
    job_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True,
        comment="Human-readable job ID, e.g. JOB-20260911-000123"
    )
    csp_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="References csp_records.csp_id"
    )
    workflow_type: Mapped[WorkflowType] = mapped_column(
        SAEnum(WorkflowType, name="workflow_type"), nullable=False
    )
    current_state: Mapped[JobState] = mapped_column(
        SAEnum(JobState, name="job_state"), nullable=False, default=JobState.DETECTED
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
        comment="User who initiated the job. NULL for automated new-CSP jobs."
    )
    error_message: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="Human-readable error description for failed states"
    )
    error_details: Mapped[str | None] = mapped_column(
        String(5000), nullable=True,
        comment="Technical error details for debugging"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True,
        comment="CSP_ID + document_set + workflow_event_id for duplicate prevention"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    document_jobs = relationship("DocumentJob", back_populates="processing_job", lazy="selectin")
    email_jobs = relationship("EmailJob", back_populates="processing_job", lazy="selectin")
    sms_jobs = relationship("SMSJob", back_populates="processing_job", lazy="selectin")
    validation_results = relationship("ValidationResult", back_populates="processing_job", lazy="selectin")

    def __repr__(self) -> str:
        return f"<ProcessingJob {self.job_id} csp={self.csp_id} state={self.current_state.value}>"
