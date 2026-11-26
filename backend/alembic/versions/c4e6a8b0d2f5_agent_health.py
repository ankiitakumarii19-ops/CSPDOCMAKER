"""Agent health: scores over time, issues, what the agents learned, chat questions (No. 252)

Adds four tables, all scoped by workspace_id:
  * agent_eval_snapshots  - one row per agent per day (its numbers, its score)
  * agent_eval_issues     - problems seen with an agent, open and resolved
  * agent_improvements    - changes the agents made by themselves (with undo)
                            or proposed for the Super Admin
  * assistant_turns       - one row per question asked in the chat

Only new tables: no existing row is read, changed or removed. Downgrade
drops the four tables.

Revision ID: c4e6a8b0d2f5
Revises: b3d5f7a9c1e4
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c4e6a8b0d2f5"
down_revision = "b3d5f7a9c1e4"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _workspace():
    return sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                     sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                     nullable=False, index=True)


def _now(name):
    return sa.Column(name, sa.DateTime(timezone=True),
                     server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "agent_eval_snapshots",
        _id(), _workspace(),
        sa.Column("agent_key", sa.String(60), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        _now("updated_at"),
        sa.UniqueConstraint("workspace_id", "agent_key", "day",
                            name="uq_agent_eval_snapshot_day"),
    )
    op.create_table(
        "agent_eval_issues",
        _id(), _workspace(),
        sa.Column("agent_key", sa.String(60), nullable=False),
        sa.Column("check_key", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="open"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("limit_value", sa.Float(), nullable=True),
        _now("first_seen_at"), _now("last_seen_at"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_eval_issues_open", "agent_eval_issues",
                    ["workspace_id", "status", "agent_key", "check_key"])
    op.create_table(
        "agent_improvements",
        _id(), _workspace(),
        sa.Column("agent_key", sa.String(60), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("change", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("automatic", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        _now("created_at"),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_agent_improvements_state", "agent_improvements",
                    ["workspace_id", "status", "kind"])
    op.create_table(
        "assistant_turns",
        _id(), _workspace(),
        sa.Column("asked_by", sa.String(255), nullable=False,
                  server_default=""),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("answered", sa.Boolean(), nullable=False),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("normalized", sa.String(500), nullable=False,
                  server_default=""),
        sa.Column("question", sa.String(500), nullable=False,
                  server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False,
                  server_default="0"),
        _now("created_at"),
    )
    op.create_index("ix_assistant_turns_when", "assistant_turns",
                    ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_assistant_turns_when", table_name="assistant_turns")
    op.drop_table("assistant_turns")
    op.drop_index("ix_agent_improvements_state",
                  table_name="agent_improvements")
    op.drop_table("agent_improvements")
    op.drop_index("ix_agent_eval_issues_open", table_name="agent_eval_issues")
    op.drop_table("agent_eval_issues")
    op.drop_table("agent_eval_snapshots")
