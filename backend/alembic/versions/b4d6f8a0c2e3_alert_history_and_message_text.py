"""Action Required history; the text of a message a person sent (No. 174)

2 Nov 2026.
  * rm_alerts: resolved_via (csp_form / verification_agent / data_quality /
    sheet_editor / sheet / auto_fill / photo / documents_made) and
    resolved_note (in words) — how the missing details were filled.
  * whatsapp_messages: body_text and sent_by — what a person typed and who,
    so the CSP's chat shows the words, not only "Message".

Additive: four nullable columns. Back up the database before running.

Revision ID: b4d6f8a0c2e3
Revises: a2c4e6f8b0d1
"""
import sqlalchemy as sa
from alembic import op

revision = "b4d6f8a0c2e3"
down_revision = "a2c4e6f8b0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rm_alerts", sa.Column(
        "resolved_via", sa.String(40), nullable=True,
        comment="How the details were filled (No. 174)"))
    op.add_column("rm_alerts", sa.Column(
        "resolved_note", sa.Text, nullable=True,
        comment="Who / what filled them, in words"))
    op.add_column("whatsapp_messages", sa.Column(
        "body_text", sa.Text, nullable=True,
        comment="The words a person sent (No. 174); NULL for set wordings"))
    op.add_column("whatsapp_messages", sa.Column(
        "sent_by", sa.String(255), nullable=True,
        comment="Who pressed Send, for a message a person sent"))


def downgrade() -> None:
    op.drop_column("whatsapp_messages", "sent_by")
    op.drop_column("whatsapp_messages", "body_text")
    op.drop_column("rm_alerts", "resolved_note")
    op.drop_column("rm_alerts", "resolved_via")
