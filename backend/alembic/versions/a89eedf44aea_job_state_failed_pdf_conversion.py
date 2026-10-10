"""job_state failed_pdf_conversion

PDF conversion is a distinct step that can fail on its own (LibreOffice
missing, a template that will not render, a timeout), and it must be
distinguishable from a generation or validation failure when someone is
looking at why a CSP did not receive their documents.

Revision ID: a89eedf44aea
Revises: 34687b6e26c0
Create Date: 2026-09-24 10:12:03.441882
"""
from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a89eedf44aea'
down_revision: Union[str, None] = '34687b6e26c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every value the enum holds after this migration, in order.
_STATES_AFTER = (
    'DETECTED', 'DATA_VALIDATING', 'DATA_VALIDATED',
    'DOCUMENT_GENERATING', 'DOCUMENT_GENERATED',
    'DOCUMENT_VALIDATING', 'DOCUMENT_VALIDATED',
    'EMAIL_VALIDATING', 'EMAIL_VALIDATED', 'READY_TO_SEND',
    'AWAITING_CONFIRMATION', 'EMAIL_SENDING', 'EMAIL_SENT',
    'SMS_SENDING', 'SMS_SENT', 'COMPLETED',
    'FAILED_DATA_VALIDATION', 'FAILED_DOCUMENT_GENERATION',
    'FAILED_DOCUMENT_VALIDATION', 'FAILED_PDF_CONVERSION',
    'FAILED_EMAIL_VALIDATION', 'FAILED_EMAIL_SENDING', 'FAILED_SMS_SENDING',
)


def upgrade() -> None:
    # PostgreSQL 12+ allows ADD VALUE inside a transaction as long as the new
    # value is not used in that same transaction; nothing here writes a row.
    op.execute(
        "ALTER TYPE job_state ADD VALUE IF NOT EXISTS 'FAILED_PDF_CONVERSION' "
        "AFTER 'FAILED_DOCUMENT_VALIDATION'"
    )


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value, so the type is rebuilt
    # without it. Any job actually parked in that state would be lost, so the
    # downgrade refuses instead of silently rewriting history.
    stuck = op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM processing_jobs "
        "WHERE current_state = 'FAILED_PDF_CONVERSION'"
    ).scalar()
    if stuck:
        raise RuntimeError(
            f"{stuck} processing job(s) are in state FAILED_PDF_CONVERSION. "
            "Resolve or delete them before downgrading this migration."
        )

    remaining = tuple(s for s in _STATES_AFTER if s != 'FAILED_PDF_CONVERSION')
    values = ", ".join(f"'{s}'" for s in remaining)
    op.execute(f"CREATE TYPE job_state_old AS ENUM ({values})")
    op.execute(
        "ALTER TABLE processing_jobs ALTER COLUMN current_state TYPE job_state_old "
        "USING current_state::text::job_state_old"
    )
    op.execute("DROP TYPE job_state")
    op.execute("ALTER TYPE job_state_old RENAME TO job_state")
