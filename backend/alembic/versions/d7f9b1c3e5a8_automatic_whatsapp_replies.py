"""Automatic WhatsApp greetings kept apart from real replies

Tracker No. 112 (15 Oct 2026): the first CSP to reply sent a WhatsApp
Business auto-greeting ("Welcome to Krishna CSC Centre…") 5 seconds after
our message. Such a reply is now kept on the message but not counted as a
response. Adds two nullable columns; nothing existing is changed.

IF NOT EXISTS so it is safe on a database where they were added by hand.

Revision ID: d7f9b1c3e5a8
Revises: c6e8a0b2d4f7
"""
from alembic import op

revision = "d7f9b1c3e5a8"
down_revision = "c6e8a0b2d4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE whatsapp_messages
            ADD COLUMN IF NOT EXISTS auto_reply_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS auto_reply_text VARCHAR(500)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE whatsapp_messages
            DROP COLUMN IF EXISTS auto_reply_text,
            DROP COLUMN IF EXISTS auto_reply_at
    """)
