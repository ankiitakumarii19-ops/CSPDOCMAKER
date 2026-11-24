"""Feature access and own roles (No. 206, Stage 2)

24 Nov 2026, Stage 2 of the configurable product plan (No. 199). The Super
Admin decides which features each role and each person has, makes own roles
(built on RM or Admin) and which CSPs each role may act on.

  access_roles        a workspace's own roles, and its choice of which CSPs
                      the built-in RM role may act on (rows "rm" / "admin"
                      appear only when changed)
  feature_access      a feature given to or taken from a role or a person
                      (no row = today's access, services/feature_catalog.py)
  workspace_members.access_role   the own role a member has (NULL = the
                      built-in RM / Admin role, as today)

Additive: two new tables and one nullable column; nothing existing changes.

Revision ID: e7a9b1c3d5f8
Revises: d6f8a0b2c4e7
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "e7a9b1c3d5f8"
down_revision = "d6f8a0b2c4e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_roles",
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_role", sa.String(20), nullable=False),
        sa.Column("record_scope", sa.String(10), nullable=False,
                  server_default="own"),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_table(
        "feature_access",
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("feature", sa.String(60), primary_key=True),
        sa.Column("subject", sa.String(300), primary_key=True),
        sa.Column("allowed", sa.Boolean, nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.add_column("workspace_members",
                  sa.Column("access_role", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_members", "access_role")
    op.drop_table("feature_access")
    op.drop_table("access_roles")
