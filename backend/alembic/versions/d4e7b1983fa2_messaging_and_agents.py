"""messaging a workspace controls, and agents that account for themselves

Messaging: a workspace chooses how it reaches its CSPs (including its own
WhatsApp account), what the message says, and can start one deliberately
rather than only waiting for a trigger.

Agents: each recurring piece of work becomes a named worker with a run
history and findings. A finding is how an agent proposes a configuration
change — it never makes one silently.

Revision ID: d4e7b1983fa2
Revises: c9f2a570e81b
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d4e7b1983fa2"
down_revision = "c9f2a570e81b"
branch_labels = None
depends_on = None


def _workspace():
    return sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                     nullable=False)


def _fk_workspace():
    return sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"],
                                   ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "message_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        _workspace(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("secret_ref", sa.String(length=120), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        _fk_workspace(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_channel_name"),
    )
    op.create_index("ix_message_channels_workspace_id", "message_channels",
                    ["workspace_id"])
    op.create_index("ix_message_channels_active", "message_channels",
                    ["active"])

    op.create_table(
        "message_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        _workspace(),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel_kind", sa.String(length=20), nullable=False,
                  server_default="whatsapp"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("languages", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("is_builtin", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        _fk_workspace(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name",
                            name="uq_message_template"),
    )
    op.create_index("ix_message_templates_workspace_id", "message_templates",
                    ["workspace_id"])
    op.create_index("ix_message_templates_active", "message_templates",
                    ["active"])

    op.create_table(
        "message_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        _workspace(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipients", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="draft"),
        sa.Column("sent_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("outcome", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("started_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _fk_workspace(),
        sa.ForeignKeyConstraint(["template_id"], ["message_templates.id"],
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["channel_id"], ["message_channels.id"],
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_campaigns_workspace_id", "message_campaigns",
                    ["workspace_id"])
    op.create_index("ix_message_campaigns_status", "message_campaigns",
                    ["status"])

    # ---- agents --------------------------------------------------------
    op.create_table(
        "agent_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        _workspace(),
        sa.Column("agent_key", sa.String(length=60), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=True),
        sa.Column("last_summary", sa.Text(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        _fk_workspace(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "agent_key",
                            name="uq_agent_state"),
    )
    op.create_index("ix_agent_states_workspace_id", "agent_states",
                    ["workspace_id"])
    op.create_index("ix_agent_states_agent_key", "agent_states", ["agent_key"])

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        _workspace(),
        sa.Column("agent_key", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("detail", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(length=255), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        _fk_workspace(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_workspace_id", "agent_runs",
                    ["workspace_id"])
    op.create_index("ix_agent_runs_agent_key", "agent_runs", ["agent_key"])

    op.create_table(
        "agent_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        _workspace(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_key", sa.String(length=60), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False,
                  server_default="info"),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="informational"),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("proposal", postgresql.JSONB(), nullable=True),
        sa.Column("subject_type", sa.String(length=60), nullable=True),
        sa.Column("subject_id", sa.String(length=255), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        _fk_workspace(),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_findings_workspace_id", "agent_findings",
                    ["workspace_id"])
    op.create_index("ix_agent_findings_run_id", "agent_findings", ["run_id"])
    op.create_index("ix_agent_findings_status", "agent_findings", ["status"])


def downgrade() -> None:
    for table in ("agent_findings", "agent_runs", "agent_states",
                  "message_campaigns", "message_templates",
                  "message_channels"):
        op.drop_table(table)
