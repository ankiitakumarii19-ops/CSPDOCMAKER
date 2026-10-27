"""Replies to what CSPs write on WhatsApp (No. 151)

27 Oct 2026: "an agent which reads their response and responds whatever they
ask; if it is not related, reply: contact your RM, with name and number."
Rules + Knowledge Base, no AI (No. 116); drafts first, a person sends them,
then a switch makes it automatic.

csp_replies holds each burst of messages and its reply. The reply wordings
are Knowledge Base entries in category "CSP replies" (every workspace), so
Admins can change them; the staff chat does not answer from that category.
Placeholders: {rm} (" <name> (<number>)" or nothing), {date}, {email}.

Revision ID: d1f3a5c7e9b2
Revises: c7e9a1b3d5f8
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "d1f3a5c7e9b2"
down_revision = "c7e9a1b3d5f8"
branch_labels = None
depends_on = None

BY = "starting set (No. 151)"
CATEGORY = "CSP replies"

# (question = the rule's name, phrasings, keywords, answer)
START = [
    ("CSP reply: the link does not open",
     "link open nahi hota\nlink nahi khul raha\nlink not opening\nlink expired",
     "link",
     "Link ki pareshani ke liye khed hai. Hum aapko abhi ek naya link bhej "
     "rahe hain - use 7 din ke andar ek baar bharein."),
    ("CSP reply: details already received",
     "", "",
     "Aapki details {date} ko humein mil chuki hain, dhanyavaad. Ab kuch aur "
     "bharne ki zaroorat nahi hai."),
    ("CSP reply: documents were emailed",
     "documents kab milenge\ncertificate nahi mila\nid card kab aayega",
     "documents, certificate, id card, appointment letter",
     "Aapke documents {date} ko {email} par email kiye gaye the. Kripya "
     "inbox aur spam folder dekhein."),
    ("CSP reply: documents not made yet",
     "", "",
     "Aapke documents aapki details poori hone ke baad aapke email par "
     "bheje jayenge."),
    ("CSP reply: uploads and other papers",
     "police verification upload\nagreement upload nahi hota",
     "upload, police verification, agreement",
     "Police verification, agreement aur doosre papers ke liye kripya apne "
     "RM{rm} se sampark karein."),
    ("CSP reply: wrong details",
     "naam galat hai\naddress change karna hai\nwrong details",
     "wrong, galat, change",
     "Details sudharne ke liye hum aapko naya link bhej rahe hain - usme "
     "sahi details bharein."),
    ("CSP reply: anything else",
     "", "",
     "Is baare mein kripya apne RM{rm} se sampark karein."),
    ("Is this message genuine?",
     "kya yeh message asli hai\nfake message\nfraud\ngenuine hai kya\n"
     "kaun bhej raha hai",
     "genuine, fake, fraud, asli",
     "Haan, yeh message Eko Bharat Ventures ki taraf se hai, SBI Kiosk CSPs "
     "ke documents ke liye. Hum kabhi OTP, PIN ya password nahi maangte."),
    ("Why did I get this message?",
     "yeh message kyu aaya\nwhy this message\nkis liye hai",
     "why message, kyu",
     "Hum check kar rahe hain ki aapki CSP details sahi hain, taaki aapka ID "
     "card, Appointment Letter aur certificates sahi bane. Kripya link khol "
     "kar apni details confirm karein."),
]


def upgrade() -> None:
    op.create_table(
        "csp_replies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("csp_id", sa.String(100), nullable=False, index=True),
        sa.Column("phone", sa.String(20), nullable=False, index=True),
        sa.Column("messages", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("last_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intents", JSONB, nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("reply_text", sa.Text, nullable=False, server_default=""),
        sa.Column("action", sa.String(30), nullable=True),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="draft"),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
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
    op.drop_table("csp_replies")
