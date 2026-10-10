"""dashboards a Super Admin builds

One dashboard is permanent — Document Operations, which reports on what the
system exists to do. The rest are built and retired as a workspace's needs
change. Retiring hides the screen and keeps the data behind it.

Revision ID: c9f2a570e81b
Revises: b2e8c4a71d30
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c9f2a570e81b"
down_revision = "b2e8c4a71d30"
branch_labels = None
depends_on = None

DEFAULT_WORKSPACE = uuid.UUID("00000000-0000-4000-8000-000000000001")


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=60), nullable=False,
                  server_default="fa-chart-line"),
        sa.Column("is_system", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_dashboard_slug"),
    )
    op.create_index("ix_dashboards_workspace_id", "dashboards", ["workspace_id"])
    op.create_index("ix_dashboards_active", "dashboards", ["active"])

    op.create_table(
        "dashboard_widgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dashboard_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("metric", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["dashboard_id"], ["dashboards.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dashboard_widgets_dashboard_id", "dashboard_widgets",
                    ["dashboard_id"])

    # The permanent one. Its widgets are seeded by the application, which
    # can read the metric registry; a migration cannot.
    op.execute(sa.text(
        "INSERT INTO dashboards (id, workspace_id, slug, name, description, "
        "icon, is_system, active, position) VALUES "
        "(:id, :ws, 'document-operations', 'Document Operations', "
        "'What has been issued, and whether it reached the CSP.', "
        "'fa-chart-line', true, true, 0)"
    ).bindparams(id=uuid.uuid4(), ws=DEFAULT_WORKSPACE))


def downgrade() -> None:
    op.drop_table("dashboard_widgets")
    op.drop_table("dashboards")
