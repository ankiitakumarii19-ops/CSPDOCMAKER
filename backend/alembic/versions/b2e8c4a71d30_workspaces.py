"""workspaces — one customer's world, isolated from every other

Until now the system served one customer and every query assumed it. This
adds the column that makes a second one possible, and puts all existing data
into the first workspace so nothing changes for them.

workspace_id is NOT NULL everywhere on purpose. A nullable tenant column
means rows that belong to nobody, and rows that belong to nobody are rows
that leak: the first query someone writes without a filter returns them to
whoever asked. Backfill, then enforce.

Revision ID: b2e8c4a71d30
Revises: a1d6f0b39c45
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2e8c4a71d30"
down_revision = "a1d6f0b39c45"
branch_labels = None
depends_on = None

# Everything that belongs to exactly one customer. document_jobs,
# email_documents and validation_results are reached only through a parent
# that is already scoped, so they are left alone rather than denormalised.
SCOPED_TABLES = (
    "csp_records",
    "stored_documents",
    "processing_jobs",
    "email_jobs",
    "document_templates",
    "data_requests",
    "rm_alerts",
    "authorization_records",
    "users",
    "sync_runs",
    "audit_logs",
)

DEFAULT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_SLUG = "sbi-kiosk-csp"
DEFAULT_NAME = "SBI Kiosk CSP"

# Tables whose csp_id points at csp_records.csp_id.
_CSP_REFERENCES = (
    ("stored_documents_csp_id_fkey", "stored_documents"),
    ("rm_alerts_csp_id_fkey", "rm_alerts"),
    ("data_requests_csp_id_fkey", "data_requests"),
)


def upgrade() -> None:
    # ---- the workspace itself ------------------------------------------
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("owner_email", sa.String(length=255), nullable=False),
        sa.Column("document_storage", sa.String(length=40), nullable=False,
                  server_default="postgres"),
        sa.Column("storage_config", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("settings", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"])
    op.create_index("ix_workspaces_owner_email", "workspaces", ["owner_email"])
    op.create_index("ix_workspaces_active", "workspaces", ["active"])

    # ---- where a workspace's records come from --------------------------
    op.create_table(
        "data_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False,
                  server_default="records"),
        sa.Column("connection", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("secret_ref", sa.String(length=120), nullable=True),
        sa.Column("column_map", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False,
                  server_default="15"),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("last_status", sa.String(length=20), nullable=False,
                  server_default="never_run"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_row_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"],
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_data_source_name"),
    )
    op.create_index("ix_data_sources_workspace_id", "data_sources",
                    ["workspace_id"])
    op.create_index("ix_data_sources_active", "data_sources", ["active"])

    # ---- the first workspace, holding everything that already exists ----
    op.execute(sa.text(
        "INSERT INTO workspaces (id, slug, name, owner_email, "
        "document_storage, storage_config, settings, active) VALUES "
        "(:id, :slug, :name, :owner, 'postgres', '{}', '{}', true)"
    ).bindparams(id=DEFAULT_ID, slug=DEFAULT_SLUG, name=DEFAULT_NAME,
                 owner="ganesh.kumar@eko.co.in"))

    # ---- scope every existing table -------------------------------------
    for table in SCOPED_TABLES:
        op.add_column(
            table,
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                      nullable=True),
        )
        # Backfill BEFORE enforcing NOT NULL: every row that exists today
        # belongs to the customer the system was built for.
        op.execute(sa.text(
            f"UPDATE {table} SET workspace_id = :id"
        ).bindparams(id=DEFAULT_ID))
        op.alter_column(table, "workspace_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_workspace", table, "workspaces",
            ["workspace_id"], ["id"], ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])

    # A CSP code is unique within a workspace, not across the world: two
    # customers may both have a record numbered 1A850466. Three tables point
    # at csp_records.csp_id, so they move to the composite key together —
    # which also means a child row can never reference a CSP in a different
    # workspace, enforced by the database rather than by care.
    for name, table in _CSP_REFERENCES:
        op.drop_constraint(name, table, type_="foreignkey")

    op.drop_index("ix_csp_records_csp_id", table_name="csp_records")
    op.create_unique_constraint(
        "uq_csp_records_workspace_csp_id", "csp_records",
        ["workspace_id", "csp_id"],
    )
    # Still wanted on its own for lookups by code.
    op.create_index("ix_csp_records_csp_id", "csp_records", ["csp_id"])

    for name, table in _CSP_REFERENCES:
        op.create_foreign_key(
            name, table, "csp_records",
            ["workspace_id", "csp_id"], ["workspace_id", "csp_id"],
            ondelete="CASCADE",
        )

    # Likewise a document code.
    op.drop_constraint("document_templates_code_key", "document_templates",
                       type_="unique")
    op.create_unique_constraint(
        "uq_document_templates_workspace_code", "document_templates",
        ["workspace_id", "code"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_document_templates_workspace_code",
                       "document_templates", type_="unique")
    op.create_unique_constraint("document_templates_code_key",
                                "document_templates", ["code"])
    for name, table in _CSP_REFERENCES:
        op.drop_constraint(name, table, type_="foreignkey")
    op.drop_index("ix_csp_records_csp_id", table_name="csp_records")
    op.drop_constraint("uq_csp_records_workspace_csp_id", "csp_records",
                       type_="unique")
    op.create_index("ix_csp_records_csp_id", "csp_records", ["csp_id"],
                    unique=True)
    for name, table in _CSP_REFERENCES:
        op.create_foreign_key(name, table, "csp_records", ["csp_id"],
                              ["csp_id"], ondelete="CASCADE")

    for table in reversed(SCOPED_TABLES):
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        op.drop_constraint(f"fk_{table}_workspace", table, type_="foreignkey")
        op.drop_column(table, "workspace_id")

    op.drop_table("data_sources")
    op.drop_table("workspaces")
