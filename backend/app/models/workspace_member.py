"""
CSP DocMaker — who belongs to which workspace, and as what

One row per person per workspace. The same email can be an RM in one
workspace and a Super Admin in another; the role travels with the row, not
with the person.

A member is added by email, before they have an account. When they sign up
the row is already waiting for them, so a Super Admin can add someone and
tell them to register without anything else to configure.

`active = false` is how access is removed. The row is kept, so the record of
who once had access — and who added them — is never lost.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum as SAEnum, ForeignKey, String, UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import UserRole
from app.workspace_context import default_workspace_id


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "email",
                         name="uq_workspace_members_workspace_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
        default=default_workspace_id,
    )
    # Always stored lower-case, so one person is one row.
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", create_type=False), nullable=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True,
    )
    # Who added them — the "Super Admin wise" grouping. NULL for the
    # workspace's creator and for rows carried over from before this existed.
    added_by_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    def __repr__(self) -> str:
        return f"<WorkspaceMember {self.email} {self.role} in {self.workspace_id}>"
