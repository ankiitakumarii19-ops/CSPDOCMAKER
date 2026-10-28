"""Failed WhatsApps sent again until they go (No. 164)

28 Oct 2026. whatsapp_messages: when a failed send was last tried again,
whether it is still tried (retry_status NULL) or not needed any more, and
what the last try did. Nothing is sent by this migration.

Additive: three columns.

Revision ID: f1a3c5e7b9d2
Revises: e5b7d9f1a3c4
"""
import sqlalchemy as sa
from alembic import op

revision = "f1a3c5e7b9d2"
down_revision = "e5b7d9f1a3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_messages", sa.Column(
        "retried_at", sa.DateTime(timezone=True), nullable=True,
        comment="When it was last tried again after failing"))
    op.add_column("whatsapp_messages", sa.Column(
        "retry_status", sa.String(20), nullable=True,
        comment="not_needed = not tried again any more; NULL = still tried"))
    op.add_column("whatsapp_messages", sa.Column(
        "retry_note", sa.Text, nullable=True,
        comment="What the last try again did"))


def downgrade() -> None:
    op.drop_column("whatsapp_messages", "retry_note")
    op.drop_column("whatsapp_messages", "retry_status")
    op.drop_column("whatsapp_messages", "retried_at")
