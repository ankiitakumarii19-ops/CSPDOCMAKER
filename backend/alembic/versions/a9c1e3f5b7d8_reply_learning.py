"""Replies: the agent's draft beside what was sent (No. 154)

27 Oct 2026: "monitor and learn what was drafted and what I replied — did
I use yours or change it". csp_replies keeps the agent's own draft, whether
the person sent it unchanged or edited it, and by how much.

Additive: three columns.

Revision ID: a9c1e3f5b7d8
Revises: f7b9d1e3a5c6
"""
import sqlalchemy as sa
from alembic import op

revision = "a9c1e3f5b7d8"
down_revision = "f7b9d1e3a5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("csp_replies", sa.Column("draft_text", sa.Text,
                                           nullable=False, server_default=""))
    op.add_column("csp_replies", sa.Column("edited", sa.Boolean, nullable=True))
    op.add_column("csp_replies", sa.Column("edit_distance", sa.Integer,
                                           nullable=True))
    # Drafts made before this: their text is the draft.
    op.execute("UPDATE csp_replies SET draft_text = reply_text "
               "WHERE status = 'draft'")


def downgrade() -> None:
    op.drop_column("csp_replies", "edit_distance")
    op.drop_column("csp_replies", "edited")
    op.drop_column("csp_replies", "draft_text")
