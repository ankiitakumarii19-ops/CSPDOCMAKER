"""WhatsApp channel through Eko's internal WhatsApp Bulk Sender

Decided 12 Oct 2026 (tracker No. 78). Adds an active, default WhatsApp
channel (provider eko_wabs) to the Eko SBI Kiosk CSP workspace; email stays
as a channel but is no longer the default. Nothing is sent by this change:
every send is still refused while the app has no public address.

Revision ID: d5a7c9e1f3b6
Revises: c3f5a7b9d2e4
"""
from alembic import op

revision = "d5a7c9e1f3b6"
down_revision = "c3f5a7b9d2e4"
branch_labels = None
depends_on = None

EKO = "(SELECT id FROM workspaces WHERE slug = 'sbi-kiosk-csp')"


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO message_channels
            (id, workspace_id, name, kind, provider, config, is_default,
             active)
        SELECT gen_random_uuid(), {EKO}, 'WhatsApp (Eko platform)',
               'whatsapp', 'eko_wabs', '{{}}'::jsonb, true, true
        WHERE {EKO} IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM message_channels
            WHERE workspace_id = {EKO} AND kind = 'whatsapp'
              AND provider = 'eko_wabs')
    """)
    op.execute(f"""
        UPDATE message_channels SET is_default = false
        WHERE workspace_id = {EKO} AND kind = 'email'
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM message_channels
        WHERE workspace_id = {EKO} AND kind = 'whatsapp'
          AND provider = 'eko_wabs'
    """)
    op.execute(f"""
        UPDATE message_channels SET is_default = true
        WHERE workspace_id = {EKO} AND kind = 'email'
    """)
