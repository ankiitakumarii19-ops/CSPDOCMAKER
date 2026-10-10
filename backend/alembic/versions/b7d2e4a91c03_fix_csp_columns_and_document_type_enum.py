"""fix csp_records columns and document_type enum drift

The initial migration (af39c78429f2) was generated before the CSP document
fields and the real document types were added to the models:

  * csp_records was created without csp_code, branch_name, branch_code,
    photo_url, module_name, rbo_name, email_id, onboarding_month and
    onboarding_year, although the model and every document generator use them.
  * the document_type enum was created with placeholder values
    DOCUMENT_A..DOCUMENT_D while the model uses CSP_ID_CARD, CSP_CERTIFICATE,
    TRAINING_CERTIFICATE and BCP.

No document_jobs row can hold a placeholder value (every insert from the
application would have been rejected), so the enum values are renamed in place.

Revision ID: b7d2e4a91c03
Revises: af39c78429f2
Create Date: 2026-09-22 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7d2e4a91c03"
down_revision: Union[str, None] = "af39c78429f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CSP_COLUMNS = [
    sa.Column("csp_code", sa.String(length=100), nullable=True,
              comment="CSP Code used in documents — may differ from csp_id"),
    sa.Column("branch_name", sa.String(length=255), nullable=True,
              comment="Branch name for ID Card, Training Certificate, BCP"),
    sa.Column("branch_code", sa.String(length=100), nullable=True,
              comment="Branch code for ID Card, Training Certificate, BCP"),
    sa.Column("photo_url", sa.String(length=500), nullable=True,
              comment="Path/URL to CSP photo — required for CSP ID Card"),
    sa.Column("module_name", sa.String(length=255), nullable=True,
              comment="Module name for BCP document"),
    sa.Column("rbo_name", sa.String(length=255), nullable=True,
              comment="RBO name for BCP document"),
    sa.Column("email_id", sa.String(length=255), nullable=True,
              comment="Email ID field for BCP document — may differ from delivery email"),
    sa.Column("onboarding_month", sa.String(length=50), nullable=True,
              comment="Onboarding month for Training Certificate and BCP"),
    sa.Column("onboarding_year", sa.String(length=10), nullable=True,
              comment="Onboarding year for Training Certificate and BCP"),
]

# (column, type, old comment, new comment) — the source moved from Excel to Google Sheets
_COMMENT_UPDATES = [
    ("csp_id", sa.String(length=100),
     "Unique CSP identifier from the Excel source",
     "Unique CSP identifier from the Google Sheet source"),
    ("onboarded_date", sa.String(length=50),
     None,
     "Full onboarding date string from Google Sheet"),
    ("source_row_identifier", sa.String(length=255),
     "Unique identifier for the source Excel row to prevent duplicate imports",
     "Unique identifier for the source Google Sheet row to prevent duplicate imports"),
]

_DOCUMENT_TYPE_RENAMES = [
    ("DOCUMENT_A", "CSP_ID_CARD"),
    ("DOCUMENT_B", "CSP_CERTIFICATE"),
    ("DOCUMENT_C", "TRAINING_CERTIFICATE"),
    ("DOCUMENT_D", "BCP"),
]


def upgrade() -> None:
    for column in _CSP_COLUMNS:
        op.add_column("csp_records", column.copy())

    for name, type_, old_comment, new_comment in _COMMENT_UPDATES:
        op.alter_column("csp_records", name, existing_type=type_,
                        comment=new_comment, existing_comment=old_comment)

    for old, new in _DOCUMENT_TYPE_RENAMES:
        op.execute(f"ALTER TYPE document_type RENAME VALUE '{old}' TO '{new}'")


def downgrade() -> None:
    for old, new in reversed(_DOCUMENT_TYPE_RENAMES):
        op.execute(f"ALTER TYPE document_type RENAME VALUE '{new}' TO '{old}'")

    for name, type_, old_comment, new_comment in reversed(_COMMENT_UPDATES):
        op.alter_column("csp_records", name, existing_type=type_,
                        comment=old_comment, existing_comment=new_comment)

    for column in reversed(_CSP_COLUMNS):
        op.drop_column("csp_records", column.name)
