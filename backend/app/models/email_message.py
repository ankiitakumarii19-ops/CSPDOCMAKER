"""
CSP DocMaker — every email the app sends to a CSP, and what became of it
(tracker No. 127, asked 21 Oct 2026: "whatever email I send, I want to track
it the same as the WhatsApp messages").

One row per email. Filled in:
  * when it is sent — to whom, which kind, sent or failed (and why);
  * when the CSP's mail app shows its pictures — opened (first time, last
    time, how many times). Many mail apps block pictures, so "not opened"
    does NOT prove it was not read; "opened" is reliable;
  * when Gmail's "delivery failed" notice comes back to the sending inbox —
    bounced, with the reason.
Staff sign-in codes (OTP) are not CSP emails and are not recorded.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

KIND_DOCUMENTS = "documents"           # the CSP's documents, attached
KIND_DETAILS = "details_request"       # please confirm / details missing
KIND_CHAT = "chat"                     # a message sent from the chat
KIND_OTHER = "other"
KINDS = (KIND_DOCUMENTS, KIND_DETAILS, KIND_CHAT, KIND_OTHER)

SENT = "sent"
FAILED = "failed"


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (Index("ix_email_messages_token", "track_token",
                            unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id)
    csp_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True,
                                                  index=True)
    csp_name: Mapped[Optional[str]] = mapped_column(String(300),
                                                    nullable=True)
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False,
                                         default="")
    # The Message-ID header we set: how a bounce notice is matched back.
    message_id: Mapped[Optional[str]] = mapped_column(String(300),
                                                      nullable=True,
                                                      index=True)
    # The secret in the "opened" picture's address.
    track_token: Mapped[str] = mapped_column(String(64), nullable=False)
    send_status: Mapped[str] = mapped_column(String(20), nullable=False)
    sent_because: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True,
        comment="Why it was sent (send_reason, No. 156); NULL = usual flow")
    send_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    last_opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    open_count: Mapped[int] = mapped_column(Integer, nullable=False,
                                            default=0)
    bounced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    bounce_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
