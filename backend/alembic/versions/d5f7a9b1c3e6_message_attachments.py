"""Photos, videos and files attached to a message to CSPs (No. 257)

Adds one table, message_attachments, scoped by workspace_id. Only a new
table: no existing row is read, changed or removed. Downgrade drops it.

Revision ID: d5f7a9b1c3e6
Revises: c4e6a8b0d2f5
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d5f7a9b1c3e6"
down_revision = "c4e6a8b0d2f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("media_kind", sa.String(20), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("uploaded_by", sa.String(255), nullable=True),
        sa.Column("platform_ref", sa.String(500), nullable=True),
        sa.Column("platform_ref_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("message_attachments")
