"""Room for two mobile numbers in one cell (No. 144)

23 Oct 2026: the Calling sheet's "CSP Mobile number" holds two numbers for
14 CSPs ("9905985993/ 7563993807"). Copied into KOData, they did not fit
csp_records.mobile (20 characters), the CSP sync's commit failed, and none
of the 512 Calling-sheet CSPs reached the database — so no verification
WhatsApp could go to them.

Revision ID: e5a7c9d1f3b6
Revises: d4f6b8c0e2a5
"""
from alembic import op
import sqlalchemy as sa

revision = "e5a7c9d1f3b6"
down_revision = "d4f6b8c0e2a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("csp_records", "mobile", type_=sa.String(50),
                    existing_type=sa.String(20), existing_nullable=True)


def downgrade() -> None:
    # Only safe while every mobile still fits in 20 characters.
    op.alter_column("csp_records", "mobile", type_=sa.String(20),
                    existing_type=sa.String(50), existing_nullable=True)
