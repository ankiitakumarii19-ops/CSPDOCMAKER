"""Alternate number, and feedback after the documents (No. 152)

27 Oct 2026. contact_fixes: a WhatsApp that did not reach the phone is tried
on the CSP's alternate number before email (alternate = the one being tried,
alternates_tried = every one tried). csp_feedback: the "did you get your
documents?" message sent the day after the documents, and the CSP's answer
(1 got them / 2 did not / 3 something is wrong). Three reply wordings for
those answers are added to the Knowledge Base's "CSP replies".

Additive: two columns, one table, Knowledge Base entries.

Revision ID: e3a5c7e9b1d4
Revises: d1f3a5c7e9b2
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e3a5c7e9b1d4"
down_revision = "d1f3a5c7e9b2"
branch_labels = None
depends_on = None

BY = "starting set (No. 152)"
CATEGORY = "CSP replies"

START = [
    ("CSP reply: feedback — got the documents", "", "",
     "Dhanyavaad! Humein khushi hai ki aapko aapke documents mil gaye."),
    ("CSP reply: feedback — did not get them", "", "",
     "Khed hai. Hum aapke documents dobara {email} par bhej rahe hain - "
     "kripya inbox aur spam folder dekhein."),
    ("CSP reply: feedback — something is wrong", "", "",
     "Khed hai. Hum aapko data verification ka link bhej rahe hain - usme jo "
     "galat hai use sudharein, phir aapke documents dobara banenge."),
]


def upgrade() -> None:
    op.add_column("contact_fixes", sa.Column("alternate", sa.String(20),
                                             nullable=True))
    op.add_column("contact_fixes", sa.Column(
        "alternates_tried", JSONB, nullable=False,
        server_default=sa.text("'[]'::jsonb")))
    op.create_table(
        "csp_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("csp_id", sa.String(100), nullable=False, index=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("documents_message_id", UUID(as_uuid=True), nullable=False),
        sa.Column("ask_status", sa.String(20), nullable=False,
                  server_default="sent"),
        sa.Column("tries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer", sa.String(5), nullable=True),
        sa.Column("answer_text", sa.Text, nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "documents_message_id",
                            name="uq_csp_feedback_message"),
    )
    bind = op.get_bind()
    workspaces = [r[0] for r in bind.execute(sa.text("SELECT id FROM workspaces"))]
    table = sa.table(
        "knowledge_entries",
        sa.column("id"), sa.column("workspace_id"),
        sa.column("question", sa.String), sa.column("phrasings", sa.Text),
        sa.column("keywords", sa.String), sa.column("answer", sa.Text),
        sa.column("category", sa.String), sa.column("active", sa.Boolean),
        sa.column("updated_by", sa.String))
    rows = []
    for w in workspaces:
        have = {r[0] for r in bind.execute(sa.text(
            "SELECT question FROM knowledge_entries WHERE workspace_id = :w "
            "AND category = :c"), {"w": w, "c": CATEGORY})}
        rows += [{"id": uuid.uuid4(), "workspace_id": w, "question": q,
                  "phrasings": p, "keywords": k, "answer": a,
                  "category": CATEGORY, "active": True, "updated_by": BY}
                 for q, p, k, a in START if q not in have]
    if rows:
        op.bulk_insert(table, rows)


def downgrade() -> None:
    bind = op.get_bind()
    for q, _p, _k, a in START:
        bind.execute(sa.text(
            "DELETE FROM knowledge_entries WHERE question = :q AND answer = :a "
            "AND category = :c AND updated_by = :by"),
            {"q": q, "a": a, "c": CATEGORY, "by": BY})
    op.drop_table("csp_feedback")
    op.drop_column("contact_fixes", "alternates_tried")
    op.drop_column("contact_fixes", "alternate")
