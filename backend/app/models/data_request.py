"""
CSP DocMaker — the link a CSP is sent to fill in their own details

A CSP has no login and must never be given one. What they get instead is a
link carrying a random token that stands for exactly one request: this CSP,
these blank fields, until this date.

Three properties this table exists to hold:

  * The token is stored HASHED, never in the clear. A link is a bearer
    credential — whoever holds it can submit — so a leaked database must not
    hand out working links. Same reasoning as a password.

  * It names the fields it was issued for. The page shows those and nothing
    else, so a link can never be turned into a way of reading a CSP's record
    or of writing a field nobody asked for.

  * It is answered once. After a submission the link stops working, which
    bounds what a forwarded or intercepted link is worth.

Nothing here grants access to any other CSP, to any document, or to the
application itself.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, ForeignKey, Index, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workspace_context import default_workspace_id

# Where the request was sent, so a failure to reach someone is visible.
VIA_WHATSAPP = "whatsapp"
VIA_EMAIL = "email"

OPEN = "open"
ANSWERED = "answered"
EXPIRED = "expired"
CANCELLED = "cancelled"


class DataRequest(Base):
    __tablename__ = "data_requests"

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
    csp_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("csp_records.csp_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # SHA-256 of the token. The token itself is in the link and nowhere else:
    # once sent it cannot be recovered from here, only verified.
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True,
        comment="SHA-256 of the link token; the token is never stored",
    )
    # The canonical field names this link may fill, as field_ownership names
    # them. A submission touching anything else is refused.
    fields: Mapped[list] = mapped_column(
        JSONB, nullable=False,
        comment="Canonical field names this link was issued for",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OPEN, index=True,
        comment="open | answered | expired | cancelled",
    )
    # How it was delivered, and to what. Kept so an unanswered request can be
    # told apart from one that never arrived.
    sent_via: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sent_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # What came back, before it was applied. Keeping it makes a wrong value
    # traceable to the submission that introduced it.
    answered_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_data_requests_csp_status", "csp_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<DataRequest {self.csp_id} {self.status} {len(self.fields or [])} field(s)>"
