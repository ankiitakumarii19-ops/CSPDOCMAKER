"""CSP photos stored in the database

Decided 12 Oct 2026 (tracker No. 47 / No. 89): a CSP's photo (the original
and the passport version printed on documents) is kept in the database as
part of the complete record. Adds a table only; nothing existing changes.

Revision ID: a3c5e7f9b1d2
Revises: e7b9d1f3a5c8
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a3c5e7f9b1d2"
down_revision = "e7b9d1f3a5c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "csp_photos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("csp_id", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "csp_id", "kind",
                            name="uq_csp_photos_workspace_csp_kind"),
        # A CSP code is unique within a workspace, so the link is both.
        sa.ForeignKeyConstraint(
            ["workspace_id", "csp_id"],
            ["csp_records.workspace_id", "csp_records.csp_id"],
            name="csp_photos_csp_fkey", ondelete="CASCADE"),
    )
    op.create_index("ix_csp_photos_workspace_id", "csp_photos", ["workspace_id"])
    op.create_index("ix_csp_photos_csp_id", "csp_photos", ["csp_id"])


def downgrade() -> None:
    op.drop_table("csp_photos")
