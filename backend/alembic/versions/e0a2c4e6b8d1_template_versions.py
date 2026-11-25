"""Template versions and categories (No. 240, SaaS upgrade Stage 5)

Adds:
  * table `document_template_versions` — what a template was before each
    change (new upload, wording edit, restore), so it can be put back.
    Empty to start: a template's current file becomes a kept version the
    first time it is changed (nothing is copied now).
  * `document_templates.category` — an optional group name for the list
    (NULL for every existing template: shown as before).

No existing row is read, changed or removed. Generation still reads only
document_templates.

Downgrade drops the table and the column.

Revision ID: e0a2c4e6b8d1
Revises: d9f1b3c5e7a0
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e0a2c4e6b8d1"
down_revision = "d9f1b3c5e7a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_template_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("template_code", sa.String(60), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("placeholder_map", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("photo_marker", sa.String(255), nullable=True),
        sa.Column("was_active", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("reason", sa.String(60), nullable=False,
                  comment="new_upload | wording_edit | restore"),
        sa.Column("saved_by", sa.String(255), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.add_column("document_templates", sa.Column(
        "category", sa.String(80), nullable=True,
        comment="Optional group on the Document Templates list"))


def downgrade() -> None:
    op.drop_column("document_templates", "category")
    op.drop_table("document_template_versions")
