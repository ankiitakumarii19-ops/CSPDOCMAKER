"""
CSP DocMaker — Audit Log Model

Complete audit trail for all significant operations.
Covers authentication, document generation, email, SMS, and admin actions.
See Section 37 for the full list of audited events.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.workspace_context import default_workspace_id


class AuditLog(Base):
    __tablename__ = "audit_logs"

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
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
        comment="Actor — NULL for system-initiated events"
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Event type: login, document_generated, email_sent, etc."
    )
    resource_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Resource category: user, csp, document, email, sms, job"
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
        comment="ID of the affected resource"
    )
    csp_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True,
        comment="CSP ID when the event relates to a specific CSP"
    )
    result: Mapped[str] = mapped_column(
        String(50), nullable=False, default="success",
        comment="Outcome: success, failure, error, denied"
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="Additional context — must not contain passwords, OTPs, or secrets"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action} result={self.result}>"
