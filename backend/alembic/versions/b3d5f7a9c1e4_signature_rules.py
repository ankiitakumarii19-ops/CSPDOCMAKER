"""Signatures chosen by rule (No. 247)

Adds:
  * table `signatures` — a workspace's signature pictures (PNG).
  * table `signature_rules` — "on this document (or every document), when
    this column of the CSP has one of these values, print this signature".
    The first active rule that matches, in `position` order, is used.
  * `document_templates.signature_spot` — where a template's signature is:
    "picture:<sha256>" (that picture inside the file is replaced) or
    "text:<paragraph text>" (that paragraph becomes the signature).
    NULL = as before (a supplied document's signature picture).

Only new things: no existing row is read, changed or removed. With no rules,
every document is made exactly as before.

Downgrade drops both tables and the column.

Revision ID: b3d5f7a9c1e4
Revises: f2b4d6a8c0e3
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3d5f7a9c1e4"
down_revision = "f2b4d6a8c0e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signatures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("image", sa.LargeBinary(), nullable=False, comment="PNG"),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "name", name="uq_signatures_name"),
    )
    op.create_table(
        "signature_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("document_code", sa.String(50), nullable=True,
                  comment="NULL = every document"),
        sa.Column("column_name", sa.String(50), nullable=False,
                  server_default="", comment="'' = every CSP"),
        sa.Column("match_values", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("signature_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("signatures.id", ondelete="RESTRICT"),
                  nullable=False, index=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.add_column("document_templates", sa.Column(
        "signature_spot", sa.String(400), nullable=True,
        comment="picture:<sha256> or text:<paragraph>; NULL = as before"))


def downgrade() -> None:
    op.drop_column("document_templates", "signature_spot")
    op.drop_table("signature_rules")
    op.drop_table("signatures")
