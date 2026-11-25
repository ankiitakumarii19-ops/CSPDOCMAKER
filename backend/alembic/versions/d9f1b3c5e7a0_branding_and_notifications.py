"""Organisation logo; each person's notifications and dashboards (No. 240, Stages 3 and 5)

Adds:
  * table `workspace_files` — a workspace's own files; today its logo
    (one per workspace and kind). Empty: every workspace keeps the app's own
    logo, exactly as before.
  * `user_preferences.notifications` — staff notifications a person switched
    off for themselves ({} = everything as before).
  * `user_preferences.dashboards` — a person's own arrangement of each
    dashboard ({} = the workspace's arrangement, as before).

Only new things: no existing row is read, changed or removed. The two new
columns default to {} for any row already there.

Downgrade drops the table and the two columns.

Revision ID: d9f1b3c5e7a0
Revises: c8e0a2b4d6f9
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d9f1b3c5e7a0"
down_revision = "c8e0a2b4d6f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("kind", sa.String(30), nullable=False, comment="logo"),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("content_type", sa.String(60), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False,
                  comment="SHA-256; also its version"),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "kind", name="uq_workspace_files_kind"),
    )
    for name, comment in (
            ("notifications", "Staff notifications this person switched off"),
            ("dashboards", "This person's own dashboard arrangement")):
        op.add_column("user_preferences", sa.Column(
            name, postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"), comment=comment))


def downgrade() -> None:
    op.drop_column("user_preferences", "dashboards")
    op.drop_column("user_preferences", "notifications")
    op.drop_table("workspace_files")
