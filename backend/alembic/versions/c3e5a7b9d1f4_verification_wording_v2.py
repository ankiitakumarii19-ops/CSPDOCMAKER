"""New first sentence for "confirm your details" (No. 136)

22 Oct 2026: Eko's WhatsApp platform only reads the first 100 templates on
the account. Other teams' templates pushed the app's approved one past that,
so the platform could not find it and failed re-creating it ("There is
already English (US) content for this template"). A slightly different
wording is a new template the platform creates (and Meta approves once).

Only the supplied wording, still starting with the old sentence, is changed;
one someone has rewritten on the Messaging screen is left alone.

Revision ID: c3e5a7b9d1f4
Revises: b2d4f6a8c0e1
"""
from alembic import op
import sqlalchemy as sa

revision = "c3e5a7b9d1f4"
down_revision = "b2d4f6a8c0e1"
branch_labels = None
depends_on = None

OLD = ("Namaste {name}, your CSP documents need your details confirmed. "
       "Please open this link,")
NEW = ("Namaste {name}, please confirm your details for your CSP documents. "
       "Open this link,")


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
