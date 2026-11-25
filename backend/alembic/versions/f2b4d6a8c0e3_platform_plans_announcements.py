"""Platform: plans, subscriptions, announcements (No. 240, SaaS upgrade Stage 6)

Adds three tables kept by the Supreme Owner:
  * `plans` — one row is added: "unlimited" (no limits, no price).
  * `workspace_subscriptions` — one row is added: Eko's workspace (slug
    sbi-kiosk-csp) on "unlimited", status "unlimited". Every other workspace
    has no row = no plan = no limits, exactly as today.
  * `platform_announcements` — empty.

No existing row is changed or removed. Nothing is charged; no payment
gateway is called.

Downgrade drops the three tables.

Revision ID: f2b4d6a8c0e3
Revises: e0a2c4e6b8d1
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f2b4d6a8c0e3"
down_revision = "e0a2c4e6b8d1"
branch_labels = None
depends_on = None

EKO = "sbi-kiosk-csp"


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_monthly_paise", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("max_documents_month", sa.Integer(), nullable=True),
        sa.Column("max_storage_mb", sa.Integer(), nullable=True),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("trial_days", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "workspace_subscriptions",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plan_key", sa.String(40), sa.ForeignKey("plans.key"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active",
                  comment="trial | active | past_due | cancelled | unlimited"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_provider", sa.String(30), nullable=False, server_default="none"),
        sa.Column("payment_customer_ref", sa.String(120), nullable=True),
        sa.Column("white_label", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("custom_domain", sa.String(253), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "platform_announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("level", sa.String(10), nullable=False, server_default="info"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO plans (key, name, description) VALUES ('unlimited', 'Unlimited', "
        "'No limits and no charge. Eko SBI Kiosk CSP is on this plan.')"))
    bind.execute(sa.text(
        "INSERT INTO workspace_subscriptions (workspace_id, plan_key, status, notes, updated_by) "
        "SELECT id, 'unlimited', 'unlimited', 'The original workspace: never limited.', "
        "'migration f2b4d6a8c0e3 (No. 240)' FROM workspaces WHERE slug = :s"
    ).bindparams(s=EKO))


def downgrade() -> None:
    op.drop_table("platform_announcements")
    op.drop_table("workspace_subscriptions")
    op.drop_table("plans")
