"""
CSP DocMaker — every WhatsApp this app sends, and what became of it

Asked for 15 Oct 2026 (tracker No. 110): an Admin wants to see, for the
details-verification, details-missing and documents-sent messages, who was
sent one, whose was rejected or never arrived, who read it, and who answered.

Before this, a send left a trace only on the data request it belonged to (and
the "documents ready" WhatsApp left none at all), so "how many did we send?"
had no answer. One row here is one message to one person.

What is filled in when:

  * at send time  — who, which message, the platform's answer (sent / waiting
                    for Meta's approval / rejected / failed) and its job id;
  * every few minutes, by message_log.refresh — Meta's own delivered / read /
                    failed status for that job, and whether the person
                    answered (filled in the form, or replied on WhatsApp).

The mobile number is stored because a reply is matched to the message by it;
it is the CSP's own number, already held on their record. It is never logged.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

# Which message it was. Same keys as MessageTemplate.purpose.
KIND_DATA_REQUEST = "data_request"        # please confirm your details
KIND_MISSING_DATA = "missing_data"        # these details are still needed
KIND_DOCUMENTS_READY = "documents_ready"  # your documents were emailed
KIND_OTHER = "other"                      # e.g. the plain WhatsApp test
KIND_FEEDBACK = "feedback"                # did you get your documents? (No. 152)
KINDS = (KIND_DATA_REQUEST, KIND_MISSING_DATA, KIND_DOCUMENTS_READY,
         KIND_FEEDBACK,
         KIND_OTHER)

# What the platform said when it was asked to send (whatsapp_platform).
SEND_SENT = "sent"
SEND_PENDING = "pending"      # wording waiting for Meta's approval — not sent
SEND_REJECTED = "rejected"    # Meta refused the wording
SEND_FAILED = "failed"

# Meta's own report afterwards (get_delivery_status).
DELIVERY_SENT = "sent"            # accepted by WhatsApp, not yet on the phone
DELIVERY_DELIVERED = "delivered"
DELIVERY_READ = "read"
DELIVERY_FAILED = "failed"        # the phone could not be reached

# How someone answered.
RESPONSE_FORM = "form"            # filled in the details form
RESPONSE_WHATSAPP = "whatsapp"    # replied on WhatsApp


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
        default=default_workspace_id,
    )
    # No foreign key on purpose: a test goes to no CSP, and a send found in
    # the platform's history may name a CSP this database does not hold.
    # Recording the message matters more than the link.
    csp_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True)
    csp_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    phone: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="91XXXXXXXXXX; used to match replies, never logged")
    kind: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
        comment="data_request | missing_data | documents_ready | other")
    is_test: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false")

    # What it belongs to, when anything.
    data_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_requests.id", ondelete="SET NULL"),
        nullable=True, index=True)
    processing_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.id", ondelete="SET NULL"),
        nullable=True)

    # At send time.
    send_status: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="sent | pending | rejected | failed")
    send_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True,
        comment="The platform's job id; looks up delivery status")
    template_name: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True)
    sent_because: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True,
        comment="Why it was sent (send_reason, No. 156); NULL = usual flow")
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="app", server_default="app",
        comment="app = recorded when sent; history = found in the platform's "
                "send history")
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        index=True)
    # No. 164: a send that failed is tried again (services/resend_failed).
    retried_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When it was last tried again after failing")
    retry_status: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="not_needed = not tried again any more; NULL = still tried")
    retry_note: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="What the last try again did")

    # Meta's report, refreshed.
    delivery_status: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="sent | delivered | read | failed; NULL = not checked yet")
    delivery_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivery_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    check_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
        comment="Why the last status check failed, if it did")

    # The answer, if any.
    responded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    response_kind: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="form | whatsapp")
    response_text: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True,
        comment="The start of a WhatsApp reply, as the CSP wrote it")

    # A reply that came within seconds — a WhatsApp Business greeting such
    # as "Welcome to Krishna CSC Centre", not a person answering (No. 112).
    # Shown, never counted as a response.
    auto_reply_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    auto_reply_text: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_whatsapp_messages_kind_sent_at", "kind", "sent_at"),
    )

    def __repr__(self) -> str:
        return (f"<WhatsAppMessage {self.kind} {self.csp_id} "
                f"{self.send_status}/{self.delivery_status}>")
