"""an RM can put an existing CSP into the automatic pipeline

Baseline CSPs are excluded from automatic processing so a first sync cannot
email an entire organisation. That protection is against doing it in bulk by
accident, not against doing it deliberately — so an RM can now enrol one and
it completes on its own from there.

Revision ID: e8c04b2719d6
Revises: d4e7b1983fa2
"""
from alembic import op
import sqlalchemy as sa

revision = "e8c04b2719d6"
down_revision = "d4e7b1983fa2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("csp_records", sa.Column(
        "auto_enrolled_at", sa.DateTime(timezone=True), nullable=True,
        comment="When an RM put this existing CSP into the automatic pipeline",
    ))
    op.add_column("csp_records", sa.Column(
        "auto_enrolled_by", sa.String(length=255), nullable=True))
    op.create_index("ix_csp_records_auto_enrolled_at", "csp_records",
                    ["auto_enrolled_at"])


def downgrade() -> None:
    op.drop_index("ix_csp_records_auto_enrolled_at", table_name="csp_records")
    op.drop_column("csp_records", "auto_enrolled_by")
    op.drop_column("csp_records", "auto_enrolled_at")
