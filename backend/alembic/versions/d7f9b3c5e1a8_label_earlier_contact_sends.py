"""Label the contact loop's earlier sends with why (No. 158)

27 Oct 2026: the "why messages were sent" box showed no bounce / alternate /
unreachable sends, because the contact loop had sent them before messages
carried a reason (No. 156). Its own records (contact_fixes: when it asked,
how, which alternate, when it sent again) say which messages they were; this
labels those messages. Only messages with no reason yet are touched.

Data only; no structure changes. Downgrade leaves the labels (they are true).

Revision ID: d7f9b3c5e1a8
Revises: b1d3f5a7c9e2
"""
from alembic import op

revision = "d7f9b3c5e1a8"
down_revision = "b1d3f5a7c9e2"
branch_labels = None
depends_on = None

WINDOW = ("BETWEEN f.asked_at - interval '2 minutes' "
          "AND f.asked_at + interval '15 minutes'")


def upgrade() -> None:
    # A bounced email -> the CSP asked on WhatsApp.
    op.execute(f"""
        UPDATE whatsapp_messages w SET sent_because = 'email_bounced'
        FROM contact_fixes f
        WHERE w.workspace_id = f.workspace_id AND w.csp_id = f.csp_id
          AND f.problem = 'email_bounced' AND f.asked_at IS NOT NULL
          AND w.sent_because IS NULL AND w.sent_at {WINDOW}""")
    # WhatsApp did not reach them -> the CSP asked by email.
    op.execute(f"""
        UPDATE email_messages e SET sent_because = 'whatsapp_unreachable'
        FROM contact_fixes f
        WHERE e.workspace_id = f.workspace_id AND e.csp_id = f.csp_id
          AND f.problem = 'whatsapp_undelivered' AND f.asked_via = 'email'
          AND f.asked_at IS NOT NULL AND e.sent_because IS NULL
          AND e.sent_at {WINDOW.replace('w.', 'e.')}""")
    # Sent to an alternate number.
    op.execute("""
        UPDATE whatsapp_messages w SET sent_because = 'alternate_number'
        FROM contact_fixes f
        WHERE w.workspace_id = f.workspace_id AND w.csp_id = f.csp_id
          AND f.problem = 'whatsapp_undelivered' AND w.sent_because IS NULL
          AND w.phone IN (SELECT jsonb_array_elements_text(f.alternates_tried))""")
    # Sent again after the number / email was corrected.
    op.execute("""
        UPDATE email_messages e SET sent_because = 'contact_corrected'
        FROM contact_fixes f
        WHERE e.workspace_id = f.workspace_id AND e.csp_id = f.csp_id
          AND f.problem = 'email_bounced' AND f.resent_at IS NOT NULL
          AND e.sent_because IS NULL AND e.kind = 'documents'
          AND e.sent_at BETWEEN f.resent_at - interval '2 minutes'
                            AND f.resent_at + interval '15 minutes'""")
    op.execute("""
        UPDATE whatsapp_messages w SET sent_because = 'contact_corrected'
        FROM contact_fixes f
        WHERE w.workspace_id = f.workspace_id AND w.csp_id = f.csp_id
          AND f.problem = 'whatsapp_undelivered' AND f.resent_at IS NOT NULL
          AND w.sent_because IS NULL AND w.kind = 'documents_ready'
          AND w.sent_at BETWEEN f.resent_at - interval '2 minutes'
                            AND f.resent_at + interval '15 minutes'""")


def downgrade() -> None:
    pass
