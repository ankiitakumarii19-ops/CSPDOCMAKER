"""Why each WhatsApp / email was sent (No. 156)

27 Oct 2026: "I want to see whether messages were sent because of a bounce,
because the CSP asked, on the alternate number because the main one has no
WhatsApp, or by email because WhatsApp was not there." whatsapp_messages and
email_messages get `sent_because` (NULL = the usual flow).

Additive: two columns.

Revision ID: b1d3f5a7c9e2
Revises: a9c1e3f5b7d8
"""
import sqlalchemy as sa
from alembic import op

revision = "b1d3f5a7c9e2"
down_revision = "a9c1e3f5b7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_messages",
                  sa.Column("sent_because", sa.String(40), nullable=True))
    op.add_column("email_messages",
                  sa.Column("sent_because", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("email_messages", "sent_because")
    op.drop_column("whatsapp_messages", "sent_because")
