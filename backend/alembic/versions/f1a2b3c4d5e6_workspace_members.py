"""Workspace members — one person, many workspaces, a role in each

Also renames the original workspace to "Eko SBI Kiosk CSP" (its slug, the
stable identifier, does not change), and carries every existing account over
as a member of the workspace it already belonged to, with the role it
already had. Nothing is deleted.

Revision ID: f1a2b3c4d5e6
Revises: e8c04b2719d6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f1a2b3c4d5e6"
down_revision = "e8c04b2719d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("role", postgresql.ENUM(name="user_role",
                                          create_type=False),
                  nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("added_by_email", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "email",
                            name="uq_workspace_members_workspace_email"),
    )
    op.create_index("ix_workspace_members_workspace_id",
                    "workspace_members", ["workspace_id"])
    op.create_index("ix_workspace_members_email",
                    "workspace_members", ["email"])
    op.create_index("ix_workspace_members_active",
                    "workspace_members", ["active"])
    op.create_index("ix_workspace_members_added_by_email",
                    "workspace_members", ["added_by_email"])

    # Every existing account becomes a member of its own workspace.
    op.execute("""
        INSERT INTO workspace_members
            (id, workspace_id, email, name, role, active)
        SELECT gen_random_uuid(), workspace_id, lower(email), name, role, true
        FROM users
    """)

    op.execute("""
        UPDATE workspaces SET name = 'Eko SBI Kiosk CSP'
        WHERE slug = 'sbi-kiosk-csp'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE workspaces SET name = 'SBI Kiosk CSP'
        WHERE slug = 'sbi-kiosk-csp'
    """)
    op.drop_table("workspace_members")
