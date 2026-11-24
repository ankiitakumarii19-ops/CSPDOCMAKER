"""Own connections: each workspace's passwords and keys, locked (No. 210)

24 Nov 2026, Stage 3 of the configurable product plan (No. 199). A
workspace's own sheet ids, mail server and WhatsApp address are settings
(workspace_settings); its passwords and keys are kept here, encrypted
(services/secret_store.py), never shown back.

Additive: one new table; nothing existing changes.

Revision ID: f8b0c2d4e6a9
Revises: e7a9b1c3d5f8
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "f8b0c2d4e6a9"
down_revision = "e7a9b1c3d5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_secrets",
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("ciphertext", sa.Text, nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("workspace_secrets")
