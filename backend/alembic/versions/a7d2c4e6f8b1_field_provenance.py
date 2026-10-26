"""Where auto-filled values came from, and every correction to them (No. 146)

26 Oct 2026. field_provenance keeps one row per CSP and automatically
filled field (INFO, Zoho, the Address tab): the value, why, and whether a
person confirmed or corrected it. field_corrections logs every correction
with its edit distance. Also: the Calling / Lead raw data job now records
its runs in sync_runs (source 'source_sheets'), so the screens can show
when it last read those sheets — no schema change needed for that.

Additive: two new tables; nothing existing changes.

Revision ID: a7d2c4e6f8b1
Revises: e5a7c9d1f3b6
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "a7d2c4e6f8b1"
down_revision = "e5a7c9d1f3b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "field_provenance",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("csp_id", sa.String(100), nullable=False, index=True),
        sa.Column("field", sa.String(50), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("detail", sa.String(500), nullable=False,
                  server_default=""),
        sa.Column("auto_value", sa.Text, nullable=False),
        sa.Column("current_value", sa.Text, nullable=False,
                  server_default=""),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="auto"),
        sa.Column("edit_distance", sa.Integer, nullable=True),
        sa.Column("checked_via", sa.String(30), nullable=True),
        sa.Column("checked_by", sa.String(255), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), index=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "csp_id", "field",
                            name="uq_field_provenance"),
    )
    op.create_table(
        "field_corrections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("csp_id", sa.String(100), nullable=False, index=True),
        sa.Column("field", sa.String(50), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("auto_value", sa.Text, nullable=False),
        sa.Column("old_value", sa.Text, nullable=False, server_default=""),
        sa.Column("new_value", sa.Text, nullable=False),
        sa.Column("edit_distance", sa.Integer, nullable=False),
        sa.Column("changed_via", sa.String(30), nullable=False),
        sa.Column("changed_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("field_corrections")
    op.drop_table("field_provenance")
