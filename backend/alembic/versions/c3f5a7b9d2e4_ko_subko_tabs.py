"""The CSP records source now reads two tabs: KOData and SUBKOData

The user renamed CSPData to KOData and added SUBKOData on 11 Oct 2026.
Display only — the sync reads the tab names from the settings.

Revision ID: c3f5a7b9d2e4
Revises: b8e2f4a6c1d3
"""
from alembic import op

revision = "c3f5a7b9d2e4"
down_revision = "b8e2f4a6c1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE data_sources
        SET connection = (connection - 'tab')
            || '{"tab": "KOData", "tabs": ["KOData", "SUBKOData"]}'::jsonb
        WHERE purpose = 'records' AND connection->>'tab' = 'CSPData'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE data_sources
        SET connection = (connection - 'tabs') || '{"tab": "CSPData"}'::jsonb
        WHERE purpose = 'records' AND connection->>'tab' = 'KOData'
    """)
