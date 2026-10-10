"""super_admin role

The person who sets a workspace up — data sources, fields, templates and who
may sign in — is not the same person who watches the dashboards. Separating
them is what lets an Admin be given monitoring access without also being able
to change what every CSP's documents say.

Revision ID: a1d6f0b39c45
Revises: f7c3b85d20a9
"""
from alembic import op

revision = "a1d6f0b39c45"
down_revision = "f7c3b85d20a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on
    # older servers, and alembic wraps migrations in one. COMMIT first.
    op.execute("COMMIT")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'SUPER_ADMIN'")


def downgrade() -> None:
    # PostgreSQL cannot remove a value from an enum. Removing it would mean
    # rebuilding the type and every column using it, which would be far more
    # destructive than leaving an unused label in place.
    pass
