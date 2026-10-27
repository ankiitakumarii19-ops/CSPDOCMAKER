"""The app fixes INFO's AO / RBO itself (No. 153)

27 Oct 2026: "the app can change the INFO sheet by itself" — fully
automatic. quality_suggestions.applied keeps every INFO cell the app
changed (where, before, after) so a change can be seen and undone;
note says why a suggestion was left for a person.

Additive: two columns.

Revision ID: f7b9d1e3a5c6
Revises: e3a5c7e9b1d4
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f7b9d1e3a5c6"
down_revision = "e3a5c7e9b1d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("quality_suggestions", sa.Column(
        "applied", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("quality_suggestions", sa.Column(
        "note", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("quality_suggestions", "note")
    op.drop_column("quality_suggestions", "applied")
