"""What a CSP changed through their details link

Tracker No. 111 (15 Oct 2026): an Admin clicking a details message on the
WhatsApp messages screen sees each asked field before and after the CSP's
answer, whether it reached the sheet, and whether they sent a photo. Adds
four nullable columns to data_requests; nothing existing is changed.

Revision ID: c6e8a0b2d4f7
Revises: b4d6f8a0c2e5
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c6e8a0b2d4f7"
down_revision = "b4d6f8a0c2e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("data_requests", sa.Column(
        "previous_values", postgresql.JSONB(), nullable=True,
        comment="The asked fields' values just before the answer was applied"))
    op.add_column("data_requests", sa.Column(
        "sheet_saved", postgresql.JSONB(), nullable=True,
        comment="Fields written to the sheet when the answer came in"))
    op.add_column("data_requests", sa.Column(
        "sheet_error", sa.Text(), nullable=True))
    op.add_column("data_requests", sa.Column(
        "photo_sent_at", sa.DateTime(timezone=True), nullable=True,
        comment="When the CSP sent their own photo through this link"))


def downgrade() -> None:
    for column in ("photo_sent_at", "sheet_error", "sheet_saved",
                   "previous_values"):
        op.drop_column("data_requests", column)
