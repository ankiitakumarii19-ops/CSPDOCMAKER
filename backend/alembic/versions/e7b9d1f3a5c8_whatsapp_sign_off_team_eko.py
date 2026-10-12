"""WhatsApp messages signed "— Team Eko"

Decided 12 Oct 2026 (tracker No. 84). The saved WhatsApp wordings that end
with the bare "— Team" now end with "— Team Eko". Only a wording that ends
exactly that way is touched, so a wording someone has rewritten on the
Messaging screen is left alone. Email wordings are not changed.

Revision ID: e7b9d1f3a5c8
Revises: d5a7c9e1f3b6
"""
from alembic import op

revision = "e7b9d1f3a5c8"
down_revision = "d5a7c9e1f3b6"
branch_labels = None
depends_on = None

OLD = "— Team"
NEW = "— Team Eko"


def _swap(old: str, new: str) -> None:
    op.execute(f"""
        UPDATE message_templates
        SET body = left(body, length(body) - {len(old)}) || '{new}'
        WHERE channel_kind = 'whatsapp'
          AND right(body, {len(old) + 2}) = E'\\n\\n{old}'
    """)


def upgrade() -> None:
    _swap(OLD, NEW)


def downgrade() -> None:
    _swap(NEW, OLD)
