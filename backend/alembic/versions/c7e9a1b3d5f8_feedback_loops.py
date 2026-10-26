"""The feedback loops: suggested INFO fixes and contact fixes (No. 150)

26 Oct 2026. quality_suggestions: a correction to an INFO-filled value seen
on several CSPs becomes a suggestion to fix INFO (accept / dismiss / fixed).
contact_fixes: a WhatsApp that did not reach the phone or an email that
bounced, the ask for the right one through the other channel, and the
resend once it is corrected.

Additive: two new tables; nothing existing changes.

Revision ID: c7e9a1b3d5f8
Revises: b3e5f7a9c1d2
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "c7e9a1b3d5f8"
down_revision = "b3e5f7a9c1d2"
branch_labels = None
depends_on = None


def _workspace():
    return sa.Column("workspace_id", UUID(as_uuid=True),
                     sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                     nullable=False, index=True)


def _stamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      nullable=False, server_default=sa.func.now())]


def upgrade() -> None:
    op.create_table(
        "quality_suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _workspace(),
        sa.Column("field", sa.String(50), nullable=False),
        sa.Column("rule", sa.String(500), nullable=False),
        sa.Column("from_value", sa.Text, nullable=False),
        sa.Column("to_value", sa.Text, nullable=False),
        sa.Column("csp_ids", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="open"),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fixed_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("workspace_id", "field", "rule", "from_value",
                            "to_value", name="uq_quality_suggestion"),
    )
    op.create_table(
        "contact_fixes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        _workspace(),
        sa.Column("csp_id", sa.String(100), nullable=False, index=True),
        sa.Column("problem", sa.String(30), nullable=False),
        sa.Column("bad_value", sa.String(320), nullable=False),
        sa.Column("failed_kind", sa.String(30), nullable=False,
                  server_default=""),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="open"),
        sa.Column("asked_via", sa.String(20), nullable=True),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("corrected_value", sa.String(320), nullable=True),
        sa.Column("resent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        *_stamps(),
        sa.UniqueConstraint("workspace_id", "csp_id", "problem", "bad_value",
                            name="uq_contact_fix"),
    )


def downgrade() -> None:
    op.drop_table("contact_fixes")
    op.drop_table("quality_suggestions")
