"""data_requests — the tokenised link a CSP fills their own details through

Revision ID: d8b4e1c06f73
Revises: c3f1a7e82b40
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d8b4e1c06f73"
down_revision = "c3f1a7e82b40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("csp_id", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False,
                  comment="SHA-256 of the link token; the token is never stored"),
        sa.Column("fields", postgresql.JSONB(), nullable=False,
                  comment="Canonical field names this link was issued for"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="open",
                  comment="open | answered | expired | cancelled"),
        sa.Column("sent_via", sa.String(length=20), nullable=True),
        sa.Column("sent_to", sa.String(length=255), nullable=True),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_values", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["csp_id"], ["csp_records.csp_id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_requests_csp_id", "data_requests", ["csp_id"])
    op.create_index("ix_data_requests_token_hash", "data_requests",
                    ["token_hash"], unique=True)
    op.create_index("ix_data_requests_status", "data_requests", ["status"])
    op.create_index("ix_data_requests_expires_at", "data_requests", ["expires_at"])
    op.create_index("ix_data_requests_csp_status", "data_requests",
                    ["csp_id", "status"])


def downgrade() -> None:
    op.drop_table("data_requests")
