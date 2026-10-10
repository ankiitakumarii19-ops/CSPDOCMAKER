"""
CSP DocMaker — Authorization Record Model

Stores synchronized authorization data from the Google Sheet.
This table mirrors the RM and Admin sheets and is the local authority
for role-based access decisions.
"""

import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.workspace_context import default_workspace_id
from app.models.enums import UserRole


class AuthorizationRecord(Base):
    __tablename__ = "authorization_records"

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
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", create_type=False), nullable=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="google_sheet",
        comment="Origin: google_sheet"
    )
    synchronized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AuthorizationRecord {self.email} role={self.role.value} active={self.active}>"
