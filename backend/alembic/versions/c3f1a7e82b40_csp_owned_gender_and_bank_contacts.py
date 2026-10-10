"""csp gender, branch contact and rbo contact

All three columns already existed in the CSPDATA sheet and were mapped to
nothing, so a blank one could be neither chased nor filled. They are needed
now that a missing field is routed to whoever can supply it: Gender to the
CSP, the two contact numbers to their RM.

Revision ID: c3f1a7e82b40
Revises: 6710620488c9
"""
from alembic import op
import sqlalchemy as sa

revision = "c3f1a7e82b40"
down_revision = "6710620488c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "csp_records",
        sa.Column("gender", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "csp_records",
        sa.Column(
            "branch_contact", sa.String(length=50), nullable=True,
            comment="Branch Contact Number — a bank fact; the INFO tab cannot supply it",
        ),
    )
    op.add_column(
        "csp_records",
        sa.Column(
            "rbo_contact", sa.String(length=50), nullable=True,
            comment="RBO Contact No. — a bank fact; the INFO tab cannot supply it",
        ),
    )


def downgrade() -> None:
    op.drop_column("csp_records", "rbo_contact")
    op.drop_column("csp_records", "branch_contact")
    op.drop_column("csp_records", "gender")
