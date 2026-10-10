"""document types become data, not an enum

Adding a fifth document meant editing a Python enum AND a Postgres enum.
An admin can now add one by uploading it, so the three columns holding a
document type move from the enum to plain text, and a document_templates
table says what each code means.

The stored values do not change: 'CSP_ID_CARD' stays 'CSP_ID_CARD', so every
row already in document_jobs, stored_documents and email_documents keeps
pointing at the same document.

Revision ID: f7c3b85d20a9
Revises: e5a9c2d41f88
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f7c3b85d20a9"
down_revision = "e5a9c2d41f88"
branch_labels = None
depends_on = None

_USERS = (
    ("document_jobs", "document_type"),
    ("stored_documents", "document_type"),
    ("email_documents", "document_type"),
)

_BUILTINS = [
    ("CSP_ID_CARD", "CSP ID Card", "ID Card.docx"),
    ("CSP_CERTIFICATE", "CSP Certificate", "CSP Certificate.docx"),
    ("TRAINING_CERTIFICATE", "Training Certificate", "Training Certificate.docx"),
    ("BCP", "Business Continuity Plan (BCP)", "BCP.docx"),
]


def upgrade() -> None:
    op.create_table(
        "document_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("placeholder_map", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("photo_marker", sa.String(length=255), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_document_templates_code", "document_templates", ["code"])
    op.create_index("ix_document_templates_active", "document_templates",
                    ["active"])

    # The enum columns become text, keeping every stored value exactly as it
    # is. USING ::text is what preserves the existing 64 documents.
    for table, column in _USERS:
        op.alter_column(
            table, column,
            existing_type=postgresql.ENUM(name="document_type"),
            type_=sa.String(length=50),
            postgresql_using=f"{column}::text",
            existing_nullable=False,
        )
    op.execute("DROP TYPE IF EXISTS document_type")

    # Seed the four supplied documents. Their placeholder maps and photo
    # markers are filled by the application, which reads them from the
    # template files themselves — a migration must not depend on those files
    # being present.
    templates = sa.table(
        "document_templates",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("filename", sa.String),
        sa.column("is_builtin", sa.Boolean),
    )
    import uuid as _uuid
    op.bulk_insert(templates, [
        {"id": _uuid.uuid4(), "code": code, "name": name,
         "filename": filename, "is_builtin": True}
        for code, name, filename in _BUILTINS
    ])


def downgrade() -> None:
    document_type = postgresql.ENUM(
        "CSP_ID_CARD", "CSP_CERTIFICATE", "TRAINING_CERTIFICATE", "BCP",
        name="document_type",
    )
    document_type.create(op.get_bind(), checkfirst=True)
    for table, column in _USERS:
        op.alter_column(
            table, column,
            existing_type=sa.String(length=50),
            type_=document_type,
            postgresql_using=f"{column}::document_type",
            existing_nullable=False,
        )
    op.drop_table("document_templates")
