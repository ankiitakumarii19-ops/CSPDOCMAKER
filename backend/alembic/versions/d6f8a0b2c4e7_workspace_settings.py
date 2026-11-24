"""Settings centre: each workspace's own settings and their history (No. 204)

23 Nov 2026, Stage 1 of the configurable product plan (No. 199). A workspace
may now set its own value for the settings in services/settings_catalog.py;
no row = the server's value, so nothing changes for anyone until a Super
Admin changes something.

Additive: two new tables; nothing existing changes.

Revision ID: d6f8a0b2c4e7
Revises: c5e7a9b1d3f4
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "d6f8a0b2c4e7"
down_revision = "c5e7a9b1d3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_settings",
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_table(
        "workspace_setting_changes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("key", sa.String(80), nullable=False, index=True),
        sa.Column("old_value", JSONB, nullable=True),
        sa.Column("new_value", JSONB, nullable=True),
        sa.Column("changed_by", sa.String(255), nullable=False),
        sa.Column("via", sa.String(20), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("workspace_setting_changes")
    op.drop_table("workspace_settings")
