"""What the Calling sheet last said for each CSP (No. 270)

Adds one nullable column, source_sheet_states.calling_seen (JSONB): the
CSPDATA columns of the CSP's Calling-sheet row as the app last read them, so
a later change there can be told apart from a value someone corrected in
CSPDATA since. No existing row is changed. Downgrade drops the column.

Revision ID: e1a3c5e7b9d2
Revises: d5f7a9b1c3e6
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e1a3c5e7b9d2"
down_revision = "d5f7a9b1c3e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_sheet_states",
                  sa.Column("calling_seen", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_sheet_states", "calling_seen")
