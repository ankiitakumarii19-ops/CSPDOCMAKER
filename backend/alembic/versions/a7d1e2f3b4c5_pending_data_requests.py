"""RM requests wait for missing data instead of failing

Adds the PENDING_DATA job state, and the documents the RM chose, so a
request with missing details is kept and finished automatically once the
sheet has them. Nothing existing is changed or removed.

Revision ID: a7d1e2f3b4c5
Revises: f1a2b3c4d5e6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a7d1e2f3b4c5"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block on older Postgres.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE job_state ADD VALUE IF NOT EXISTS 'PENDING_DATA'")
    op.add_column("processing_jobs", sa.Column(
        "requested_documents", postgresql.JSONB(), nullable=True,
        comment="Document types the RM chose; kept while waiting for data",
    ))


def downgrade() -> None:
    # Postgres cannot drop one value from an enum; PENDING_DATA stays.
    op.drop_column("processing_jobs", "requested_documents")
