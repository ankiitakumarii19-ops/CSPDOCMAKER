"""
CSP DocMaker — signatures chosen by rule (No. 247)

Signature      a workspace's signature picture (PNG, kept in the database).
SignatureRule  "on this document (or every document), when this column of
               the CSP has one of these values, print this signature".
               The first active rule that matches, by position, wins.
               column_name '' = every CSP (a catch-all, kept last).

Both scoped by workspace_id (workspace_context): one organisation never
sees or uses another's signatures. Where a template's signature sits is
document_templates.signature_spot.
"""

import uuid
from datetime import datetime

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, LargeBinary,
                        String, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class Signature(Base):
    __tablename__ = "signatures"
    __table_args__ = (UniqueConstraint("workspace_id", "name",
                                       name="uq_signatures_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False,
                                         comment="PNG")
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)


class SignatureRule(Base):
    __tablename__ = "signature_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    document_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="NULL = every document")
    column_name: Mapped[str] = mapped_column(
        String(50), nullable=False, default="", comment="'' = every CSP")
    match_values: Mapped[list] = mapped_column(JSONB, nullable=False,
                                               default=list)
    signature_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signatures.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)
