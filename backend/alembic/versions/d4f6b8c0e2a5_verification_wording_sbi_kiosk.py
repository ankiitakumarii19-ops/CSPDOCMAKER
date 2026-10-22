"""New first sentence for the "SBI Kiosk" confirm-your-details wording (No. 137)

Same reason as c3e5a7b9d1f4 (the WhatsApp platform reads only the first 100
templates, so it no longer finds the approved one): a workspace whose
wording says "your SBI Kiosk CSP documents" was not matched by that update.

Revision ID: d4f6b8c0e2a5
Revises: c3e5a7b9d1f4
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f6b8c0e2a5"
down_revision = "c3e5a7b9d1f4"
branch_labels = None
depends_on = None

OLD = ("Namaste {name}, your SBI Kiosk CSP documents need your details "
       "confirmed. Please open this link,")
NEW = ("Namaste {name}, please confirm your details for your SBI Kiosk CSP "
       "documents. Open this link,")


def _swap(old: str, new: str) -> None:
    op.get_bind().execute(sa.text("""
        UPDATE message_templates
        SET body = :new || substr(body, length(:old) + 1)
        WHERE purpose = 'data_request'
          AND left(body, length(:old)) = :old
    """), {"old": old, "new": new})


def upgrade() -> None:
    _swap(OLD, NEW)


def downgrade() -> None:
    _swap(NEW, OLD)
