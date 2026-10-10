"""
CSP DocMaker — how a workspace talks to its CSPs

Three things, deliberately separate:

  CHANNEL   how a message physically leaves — WhatsApp through a provider,
            or email. A workspace can bring its own WhatsApp account rather
            than share one.

  TEMPLATE  what it says. Alerting a CSP that their details are missing is
            universal — every workspace gets it — but the wording, the
            languages and the tone belong to the customer, not to this code.

  CAMPAIGN  one deliberate send: these people, this template, now. Separate
            from the automatic alerting so a Super Admin can say "ask
            everybody for their documents" without waiting for a trigger.

Credentials are never stored here. `secret_ref` names an environment key and
the value is read when a message is sent, so a database backup or a careless
screen share does not leak a workspace's WhatsApp token.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.workspace_context import default_workspace_id

# How a message leaves.
WHATSAPP = "whatsapp"
EMAIL = "email"
CHANNEL_KINDS = (WHATSAPP, EMAIL)

# Who carries it.
PROVIDER_EKO_WABS = "eko_wabs"        # Eko's internal bulk sender
PROVIDER_META_CLOUD = "meta_cloud"    # a workspace's own Meta account
PROVIDER_SMTP = "smtp"
PROVIDERS = (PROVIDER_EKO_WABS, PROVIDER_META_CLOUD, PROVIDER_SMTP)

# What a message is for. These keys are fixed because the system triggers
# them; the wording behind each is not.
PURPOSE_DATA_REQUEST = "data_request"        # please confirm your details
PURPOSE_MISSING_DATA = "missing_data"        # something is missing
PURPOSE_DOCUMENTS_READY = "documents_ready"  # here are your documents
PURPOSE_CUSTOM = "custom"                    # whatever a Super Admin writes

PURPOSES = (PURPOSE_DATA_REQUEST, PURPOSE_MISSING_DATA,
            PURPOSE_DOCUMENTS_READY, PURPOSE_CUSTOM)

# Campaign states.
DRAFT = "draft"
SENDING = "sending"
SENT = "sent"
PARTIAL = "partial"
FAILED = "failed"


class MessageChannel(Base):
    __tablename__ = "message_channels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="whatsapp | email")
    provider: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="eko_wabs | meta_cloud | smtp",
    )
    # Endpoint, sender id, phone number id — whatever the provider needs.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # The NAME of the environment key holding this channel's credential.
    secret_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # The one used when a message does not name a channel.
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True)

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_channel_name"),
    )

    def __repr__(self) -> str:
        return f"<MessageChannel {self.kind}:{self.provider} {self.name}>"


class MessageTemplate(Base):
    __tablename__ = "message_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id,
    )
    purpose: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="data_request | missing_data | documents_ready | custom")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WHATSAPP)

    # The message. {name}, {link} and {fields} are substituted; anything
    # else is left alone so a stray brace cannot blank a message.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Which languages the body contains, for the record.
    languages: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list)

    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True)
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Supplied with the system; editable but not deletable")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_message_template"),
    )

    def __repr__(self) -> str:
        return f"<MessageTemplate {self.purpose}:{self.name}>"


class MessageCampaign(Base):
    __tablename__ = "message_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True, default=default_workspace_id,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("message_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("message_channels.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Who it went to, as CSP codes. Recorded rather than recomputed, so the
    # history still makes sense after the records change.
    recipients: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DRAFT, index=True)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0)
    # Why each one that did not go, did not go.
    outcome: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    started_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    template: Mapped["MessageTemplate"] = relationship(lazy="selectin")
    channel: Mapped["MessageChannel"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<MessageCampaign {self.name} {self.status}>"
