"""Calling and Lead raw data sheets: the app's memory of them, and a hold

Tracker No. 121 (21 Oct 2026). Eko's old CSPs come from the Calling sheet
and new ones from the Lead raw data sheet once they are "Go Live Done".
source_sheet_states remembers what each sheet last said about each CSP (so a
change to live can be noticed) and whether the CSP was copied into CSPDATA.
csp_records.send_hold says why nothing may be sent to a CSP right now.

Additive: one new table, one nullable column; nothing existing changes.

Revision ID: f9b1d3e5a7c2
Revises: e8a0c2d4f6b9
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "f9b1d3e5a7c2"
down_revision = "e8a0c2d4f6b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_sheet_states",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("csp_code", sa.String(50), nullable=False),
        sa.Column("in_calling", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("calling_status", sa.String(100), nullable=True),
        sa.Column("in_lead", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("lead_remarks", sa.String(300), nullable=True),
        sa.Column("lead_live", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("baseline_live", sa.Boolean, nullable=False,
                  server_default=sa.false()),
        sa.Column("went_live_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_as", sa.String(20), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("zoho_filled", JSONB, nullable=True),
        sa.Column("hold_reason", sa.Text, nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "csp_code",
                            name="uq_source_sheet_state_code"),
    )
    op.add_column("csp_records", sa.Column("send_hold", sa.Text,
                                           nullable=True))


def downgrade() -> None:
    op.drop_column("csp_records", "send_hold")
    op.drop_table("source_sheet_states")
