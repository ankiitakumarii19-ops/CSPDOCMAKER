"""which documents the CSP already holds

Answered by the CSP on their own form so the system does not re-issue a
document someone already has. Text, not boolean, because the sheet sync
compares every field against its cell as text.

Revision ID: e5a9c2d41f88
Revises: d8b4e1c06f73
"""
from alembic import op
import sqlalchemy as sa

revision = "e5a9c2d41f88"
down_revision = "d8b4e1c06f73"
branch_labels = None
depends_on = None

_COLUMNS = ("has_id_card", "has_csp_certificate",
            "has_training_certificate", "has_bcp")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("csp_records",
                      sa.Column(name, sa.String(length=10), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("csp_records", name)
