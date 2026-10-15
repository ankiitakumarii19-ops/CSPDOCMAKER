"""Every WhatsApp sent, and what became of it

Tracker No. 110 (15 Oct 2026): one row per WhatsApp message to one person —
details verification, details missing, documents sent — with the platform's
answer at send time, Meta's delivered / read status, and whether the person
answered. Only adds a table; nothing existing is changed.

Revision ID: b4d6f8a0c2e5
Revises: a3c5e7f9b1d2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b4d6f8a0c2e5"
down_revision = "a3c5e7f9b1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("csp_id", sa.String(100), nullable=True),
        sa.Column("csp_name", sa.String(300), nullable=True),
        sa.Column("phone", sa.String(20), nullable=False,
                  comment="91XXXXXXXXXX; used to match replies, never logged"),
        sa.Column("kind", sa.String(30), nullable=False,
                  comment="data_request | missing_data | documents_ready | other"),
        sa.Column("is_test", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("data_request_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("data_requests.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("processing_job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("processing_jobs.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("send_status", sa.String(20), nullable=False,
                  comment="sent | pending | rejected | failed"),
        sa.Column("send_error", sa.Text(), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True,
                  comment="The platform's job id; looks up delivery status"),
        sa.Column("template_name", sa.String(200), nullable=True),
        sa.Column("source", sa.String(20), nullable=False,
                  server_default="app",
                  comment="app = recorded when sent; history = found in the "
                          "platform's send history"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("delivery_status", sa.String(20), nullable=True,
                  comment="sent | delivered | read | failed; NULL = not "
                          "checked yet"),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("delivery_updated_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_error", sa.Text(), nullable=True,
                  comment="Why the last status check failed, if it did"),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_kind", sa.String(20), nullable=True,
                  comment="form | whatsapp"),
        sa.Column("response_text", sa.String(500), nullable=True,
                  comment="The start of a WhatsApp reply, as the CSP wrote it"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("job_id", name="uq_whatsapp_messages_job_id"),
    )
    op.create_index("ix_whatsapp_messages_workspace_id", "whatsapp_messages",
                    ["workspace_id"])
    op.create_index("ix_whatsapp_messages_csp_id", "whatsapp_messages",
                    ["csp_id"])
    op.create_index("ix_whatsapp_messages_kind", "whatsapp_messages", ["kind"])
    op.create_index("ix_whatsapp_messages_send_status", "whatsapp_messages",
                    ["send_status"])
    op.create_index("ix_whatsapp_messages_sent_at", "whatsapp_messages",
                    ["sent_at"])
    op.create_index("ix_whatsapp_messages_data_request_id",
                    "whatsapp_messages", ["data_request_id"])
    op.create_index("ix_whatsapp_messages_kind_sent_at", "whatsapp_messages",
                    ["kind", "sent_at"])


def downgrade() -> None:
    op.drop_table("whatsapp_messages")
