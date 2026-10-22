"""Every email sent to a CSP, and what became of it (sent, opened, bounced)

Tracker No. 127 (21 Oct 2026). One new table; nothing existing changes.

Revision ID: b2d4f6a8c0e1
Revises: f9b1d3e5a7c2
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b2d4f6a8c0e1"
down_revision = "f9b1d3e5a7c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("csp_id", sa.String(100), nullable=True, index=True),
        sa.Column("csp_name", sa.String(300), nullable=True),
        sa.Column("to_email", sa.String(320), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False,
                  server_default=""),
        sa.Column("message_id", sa.String(300), nullable=True, index=True),
        sa.Column("track_token", sa.String(64), nullable=False),
        sa.Column("send_status", sa.String(20), nullable=False),
        sa.Column("send_error", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_opened_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("open_count", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bounce_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_email_messages_token", "email_messages",
                    ["track_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_email_messages_token", table_name="email_messages")
    op.drop_table("email_messages")
