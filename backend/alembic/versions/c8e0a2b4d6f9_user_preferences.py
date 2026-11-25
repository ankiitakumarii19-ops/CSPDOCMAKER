"""Each person's own look (No. 240, SaaS upgrade Stage 2)

Adds the table `user_preferences`: one row per person (email), holding the
appearance choices they made on Settings -> Appearance. A new, empty table:
no existing row anywhere is read, changed or removed. Without a row a person
sees the workspace's look, exactly as before.

Downgrade drops the table (people's own looks are lost; nothing else).

Revision ID: c8e0a2b4d6f9
Revises: a9c1e3f5b7d0
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c8e0a2b4d6f9"
down_revision = "a9c1e3f5b7d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("email", sa.String(255), primary_key=True),
        sa.Column("appearance", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb"),
                  comment="The person's own look; only the choices they changed"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
