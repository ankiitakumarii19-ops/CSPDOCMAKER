"""
CSP DocMaker — replies to what CSPs write on WhatsApp (No. 151)

One row per burst of WhatsApp messages from one CSP (messages close together
are answered once). The reply agent (services/csp_replies.py) reads them,
works out what they are about by fixed rules and the Knowledge Base — no AI
— and writes the reply. In "draft" mode a person sends, edits or skips it;
in "auto" mode it goes out by itself.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id


class CspReply(Base):
    __tablename__ = "csp_replies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    csp_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="91XXXXXXXXXX; never logged")
    messages: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="What the CSP wrote: [{at, text, type}], oldest first")
    last_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="When the newest of those messages came in")
    intents: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="What the agent understood, e.g. ['link', 'upload']")
    reply_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # No. 154: the agent's own draft, and what the person did with it.
    draft_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    edited: Mapped[Optional[bool]] = mapped_column(nullable=True)
    edit_distance: Mapped[Optional[int]] = mapped_column(nullable=True)
    action: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True,
        comment="Done when the reply is sent: fresh_link, or none")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft",
        comment="draft, sent, skipped, failed or expired")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)
