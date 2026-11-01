"""Profile pictures (No. 171)

1 Nov 2026. user_photos: one optional picture per signed-in person, keyed
by email. Nothing else changes; with no row the screens show initials.

Additive: one new table. Back up the database before running.

Revision ID: a2c4e6f8b0d1
Revises: f1a3c5e7b9d2
"""
import sqlalchemy as sa
from alembic import op

revision = "a2c4e6f8b0d1"
down_revision = "f1a3c5e7b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_photos",
        sa.Column("email", sa.String(255), primary_key=True),
        sa.Column("image", sa.LargeBinary, nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False,
                  comment="SHA-256; also the picture's version"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_photos")
