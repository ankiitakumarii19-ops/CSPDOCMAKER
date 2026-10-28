"""Feedback answer 2 also gets the data verification link (No. 163)

28 Oct 2026. A CSP who answers 2 ("did not get the documents") gets the
documents email again AND the data verification link, so a wrong email can
be corrected. The Knowledge Base wording for that reply says so — changed
only where it is still the starting wording (an Admin's own edit is kept).
Replies still waiting (drafts) for answer 2 get the link added to what they
do when sent. Nothing is sent by this migration.

Revision ID: e5b7d9f1a3c4
Revises: d7f9b3c5e1a8
"""
import sqlalchemy as sa
from alembic import op

revision = "e5b7d9f1a3c4"
down_revision = "d7f9b3c5e1a8"
branch_labels = None
depends_on = None

QUESTION = "CSP reply: feedback — did not get them"
OLD = ("Khed hai. Hum aapke documents dobara {email} par bhej rahe hain - "
       "kripya inbox aur spam folder dekhein.")
NEW = (OLD + " Saath hi data verification ka link bhej rahe hain - agar "
       "aapka email galat hai to usme sahi email bharein.")
BY = "No. 163: answer 2 also gets the link"


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE knowledge_entries SET answer = :new, updated_by = :by "
        "WHERE category = 'CSP replies' AND question = :q AND answer = :old"
    ).bindparams(new=NEW, by=BY, q=QUESTION, old=OLD))
    op.execute(sa.text(
        "UPDATE csp_replies SET action = 'resend_documents,fresh_link' "
        "WHERE status = 'draft' AND intents ? 'feedback_2' "
        "AND action = 'resend_documents'"))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE knowledge_entries SET answer = :old "
        "WHERE category = 'CSP replies' AND question = :q AND answer = :new"
    ).bindparams(new=NEW, old=OLD, q=QUESTION))
    op.execute(sa.text(
        "UPDATE csp_replies SET action = 'resend_documents' "
        "WHERE status = 'draft' AND intents ? 'feedback_2' "
        "AND action = 'resend_documents,fresh_link'"))
