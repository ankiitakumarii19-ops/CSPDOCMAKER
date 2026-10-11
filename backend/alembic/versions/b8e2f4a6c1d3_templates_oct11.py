"""Built-in templates as the user re-made them on 11 Oct 2026

The CSP Certificate became the Appointment Letter (the internal code stays
CSP_CERTIFICATE so stored documents keep their type); two BCP placeholders
were renamed in Word; both photo boxes are now a 35 x 45 mm table cell whose
text reads "Affix Passport Size Photo (35 × 45 mm)".

Only the four built-in rows are touched.

Revision ID: b8e2f4a6c1d3
Revises: a7d1e2f3b4c5
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "b8e2f4a6c1d3"
down_revision = "a7d1e2f3b4c5"
branch_labels = None
depends_on = None

MARKER = "Affix Passport Size Photo (35 × 45 mm)"
BCP_MAP = {
    "CSP Name": "csp_name", "CSP Code": "csp_code",
    "Branch Name": "branch_name", "Branch Code": "branch_code",
    "AO": "ao", "RBO Name": "rbo_name", "Address": "address",
    "CSP Contact Number": "mobile", "CSP Email ID": "email",
    "Making Month, year": "certificate_month_year",
    "ASM": "asm_name", "ASM Email": "asm_email",
    "ASM Contact Number": "asm_contact",
}


def _set(code, **values):
    sets = ", ".join(f"{k} = :{k}" for k in values)
    op.get_bind().execute(
        sa.text(f"UPDATE document_templates SET {sets}, updated_at = now() "
                f"WHERE code = :code AND is_builtin"),
        {"code": code, **values})


def upgrade() -> None:
    _set("CSP_CERTIFICATE", name="Appointment Letter",
         filename="Appointment__Letter.docx")
    _set("CSP_ID_CARD", photo_marker=MARKER)
    _set("TRAINING_CERTIFICATE", photo_marker=MARKER)
    op.get_bind().execute(
        sa.text("UPDATE document_templates SET placeholder_map = "
                "CAST(:m AS jsonb), updated_at = now() "
                "WHERE code = 'BCP' AND is_builtin"),
        {"m": json.dumps(BCP_MAP)})


def downgrade() -> None:
    _set("CSP_CERTIFICATE", name="CSP Certificate",
         filename="CSP_Certificate.docx")
    _set("CSP_ID_CARD", photo_marker="Affix Passport Size Photo (35 x 45 mm)")
    _set("TRAINING_CERTIFICATE", photo_marker="Photo")
