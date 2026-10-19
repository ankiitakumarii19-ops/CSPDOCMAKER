"""The chat's Knowledge Base, with a starting set of answers

Tracker No. 116 (19 Oct 2026): the ask-anything chat no longer uses an AI
model. Process questions are answered from knowledge_entries, which Admins
and Super Admins keep on Admin -> Knowledge Base; questions the chat could
not answer are counted in knowledge_misses.

Every workspace that exists now gets the starting entries below, written
from the decisions in PROJECT-REGISTER.md. A workspace made later starts
empty (its process may differ). Two new tables; nothing existing changes.

Revision ID: e8a0c2d4f6b9
Revises: d7f9b1c3e5a8
"""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "e8a0c2d4f6b9"
down_revision = "d7f9b1c3e5a8"
branch_labels = None
depends_on = None

# (category, question, other phrasings, keywords, answer)
START = [
    ("Documents", "Which documents does the app make?",
     "what documents are made\nlist of documents\nkaun se documents bante hain",
     "documents, id card, appointment letter, training certificate, bcp",
     "Four PDFs for each CSP:\n- **ID Card**\n- **Appointment Letter** "
     "(replaced the CSP Certificate on 11 Oct 2026)\n- **Training "
     "Certificate**\n- **BCP** — only for a KO, never for a Sub-KO"),
    ("Documents", "What is a BCP?",
     "bcp meaning\nbcp kya hai\nwhat does bcp mean",
     "bcp",
     "The BCP is one of the four CSP documents. It is made only for a **KO**; "
     "a Sub-KO never gets one. It shows the CSP's ASM details and the month "
     "the CSP has been operational since, so the ASM name, email and contact "
     "number must be on record before it can be made."),
    ("Documents", "What is a KO and a Sub-KO?",
     "difference between ko and sub ko\nko sub ko kya hai\nko vs sub-ko",
     "ko, sub ko, subko, kodata, subkodata",
     "A **KO** has an 8-character code and is in the sheet's **KOData** tab. "
     "A **Sub-KO** has its KO's code plus 1 or 2 characters (9–10) and is in "
     "the **SUBKOData** tab. The Training Certificate says KO or Sub-KO by "
     "the code's length, and only a KO gets a BCP."),
    ("Documents", "What date is printed on the certificates?",
     "certificate date\nwhich date on certificate\ndate on documents",
     "date",
     "Always the day the document is made — for every CSP."),
    ("Documents", "How are documents made for a new CSP?",
     "new csp documents\nautomatic documents\nnaye csp ke documents",
     "new csp, automatic",
     "When a new CSP is added to the Google Sheet, the app picks it up "
     "(the sheet is read every minute). If every detail and the photo are "
     "there, the documents are made and emailed automatically, usually "
     "within about 3 minutes. If something is missing, the CSP is asked for "
     "it and the documents follow once it arrives. CSPs that were already in "
     "the sheet on day one are not emailed automatically."),
    ("Documents", "How does an RM get documents for an existing CSP?",
     "rm request documents\nhow to make documents\ndocuments kaise banaye",
     "rm, request, existing",
     "In the **RM Portal**, search the CSP and choose which documents to "
     "make. The RM fills in nothing: if a detail is missing, the request "
     "stays **Pending** and the CSP is asked on WhatsApp."),
    ("Documents", "Why is a document request pending?",
     "request pending\nwhy pending\ndocuments pending kyun",
     "pending",
     "A request stays **Pending** when a detail the documents need, or the "
     "photo, is missing. The CSP is asked for it on WhatsApp with a private "
     "link to their details form. When the answer reaches the sheet, the "
     "documents are made and sent automatically (checked every 3 minutes). "
     "Ask the chat \"what is missing for <CSP code>\" to see exactly what."),
    ("Documents", "How do I fix a wrong detail on a document?",
     "wrong detail on document\ncorrect a document\ngalat detail",
     "wrong, correct, fix, mistake",
     "Correct the cell in the Google Sheet (KOData or SUBKOData tab), then "
     "make the document again. The new version is stored next to the old "
     "one; nothing is overwritten."),
    ("Documents", "Where are the documents stored?",
     "where are pdfs saved\ndocuments kahan hai\ndocument storage",
     "stored, storage, folder",
     "Every PDF is kept in the app's database, and also on the server in "
     "**CSP_Documents/<CSP name> (<CSP code>)/**. Every version is kept. "
     "Ask the chat \"documents of <CSP code>\" to download them, or use the "
     "Database page."),
    ("Documents", "How are documents delivered to the CSP?",
     "how does csp get documents\ndocuments email\ndocuments kaise milte hain",
     "delivered, email",
     "By email, as PDFs, from **Eko Bharat Ventures Pvt Ltd**. A WhatsApp "
     "notice is sent as well when the WhatsApp 'documents ready' wording is "
     "approved."),
    ("Photos", "What size is the photo on the documents?",
     "photo size\npassport photo\nphoto kitna bada",
     "size, passport, 35, 45",
     "Passport size: **35 × 45 mm**, white background, head and shoulders. "
     "It is made on the server from the CSP's own photo — the face is never "
     "changed and no AI is used."),
    ("Photos", "Where does the app get a CSP's photo?",
     "photo source\nphoto kahan se aata hai\nhow is photo taken",
     "photo, zoho, sheet",
     "From Zoho (including Leads), from the Photo column of the Google Sheet "
     "(checked every 15 minutes), from an RM's upload on the CSP's card, or "
     "from the CSP's own details form."),
    ("Photos", "What happens if a CSP has no photo?",
     "no photo\nphoto nahi hai\nmissing photo",
     "no photo",
     "The ID Card and Training Certificate are not made without a real "
     "photo — a blank photo box is never used. The request waits and the "
     "CSP is asked for the photo."),
    ("Access", "Who can log in to the app?",
     "login access\nwho can use the app\nkaun login kar sakta hai",
     "login, access, authorization",
     "Only people listed in the **Authorization** sheet (RMs and Admins) and "
     "Super Admins. Nobody gets an account made for them; a Super Admin can "
     "add people on the **Access** screen."),
    ("Access", "What can an RM see and do?",
     "rm access\nrm permissions\nrm kya kar sakta hai",
     "rm",
     "An RM requests documents for their own CSPs (and for CSPs with no RM "
     "found), uploads photos, uses Sheets (CSP tabs) and the Database page "
     "(read-only), and uses this chat for their own CSPs."),
    ("Access", "What can an Admin do?",
     "admin access\nadmin permissions",
     "admin",
     "Admins see the dashboards and the WhatsApp messages screen, edit "
     "message wordings and document templates, build dashboards, use Sheets "
     "and the Database page, and keep this Knowledge Base. Agents and Access "
     "are for Super Admins only."),
    ("Access", "How long does a sign-in last?",
     "logged out\nsession expired\nkitni der login rehta hai",
     "sign in, session, logout",
     "24 hours, or until you log out. Logging out in one tab logs you out of "
     "all tabs."),
    ("Access", "I did not get the login code",
     "otp not received\ncode nahi aaya\nresend code",
     "otp, code, resend",
     "The code is sent to your email. Check spam, then press **Resend code** "
     "(it can be pressed again after 30 seconds)."),
    ("WhatsApp", "Which WhatsApp messages does the app send?",
     "whatsapp messages types\nkaun se whatsapp jaate hain",
     "whatsapp",
     "Three: **Data verification** (please confirm your details), **Data "
     "missing** (these details are still needed) and **Documents sent**. "
     "Admin → **WhatsApp messages** shows who got each one and whether it "
     "was delivered, read and answered."),
    ("WhatsApp", "What counts as a CSP responding?",
     "responded meaning\nresponse count\nauto reply",
     "responded, response, auto reply",
     "Filling in the details form, or replying on WhatsApp. An automatic "
     "WhatsApp Business greeting that arrives within 60 seconds of our "
     "message is shown but not counted."),
    ("WhatsApp", "Why is a WhatsApp message late or not received?",
     "whatsapp late\nwhatsapp nahi aaya\nmessage not delivered",
     "late, not received",
     "The WhatsApp number is shared with other Eko teams, so messages can "
     "queue behind theirs. A new wording also waits once for Meta's approval "
     "(minutes to a day). Ask \"WhatsApp status of <CSP code>\" to see what "
     "happened to that CSP's messages."),
    ("Sheet", "How often is the Google Sheet read?",
     "sheet sync\nsheet update time",
     "sheet, sync",
     "Every minute. The sheet is always taken as correct."),
    ("Sheet", "Where do the DC, ASM and RM names come from?",
     "dc asm rm source\ninfo tab",
     "info, dc, asm, rm",
     "From the sheet's **INFO** tab, matched by district, when the CSP's own "
     "row does not have them."),
    ("Sheet", "What are RBO, LHO and AO?",
     "rbo meaning\nlho meaning\nao meaning",
     "rbo, lho, ao",
     "SBI's offices above the CSP's branch: **RBO** — Regional Business "
     "Office; **AO** — Administrative Office; **LHO** — Local Head Office. "
     "Ask \"RBO number of <CSP code>\" for a CSP's own RBO."),
    ("Chat", "How does this chat work?",
     "is this ai\nhow are answers made\nchat kaise kaam karta hai",
     "chat, ai",
     "No AI. Questions about a CSP are answered straight from the app's "
     "records; questions about the process come from this Knowledge Base, "
     "written by Admins. The same question always gets the same answer. "
     "RMs get answers about their own CSPs only."),
    ("Chat", "How do I message a CSP from the chat?",
     "send message to csp\ncsp ko message kaise bheje",
     "message, remind",
     "Ask e.g. **Remind 1A851727 to send their photo by Friday**. The chat "
     "shows a draft — it goes by WhatsApp if the CSP has a mobile number, "
     "otherwise by email — and nothing is sent until you press **Send**."),
    ("Chat", "How do I add an answer to the chat?",
     "add knowledge\nteach the chat\nnew answer",
     "knowledge base",
     "Admins and Super Admins: open Admin → **Knowledge Base** and press "
     "**Add**. Questions the chat could not answer are listed there too."),
    ("General", "What is a CSP?",
     "csp meaning\ncsp kya hai",
     "csp",
     "A Customer Service Point: an SBI Kiosk Banking agent working with Eko. "
     "This app makes and sends their ID Card, Appointment Letter, Training "
     "Certificate and BCP."),
]


def upgrade() -> None:
    op.create_table(
        "knowledge_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("question", sa.String(300), nullable=False),
        sa.Column("phrasings", sa.Text, nullable=False, server_default=""),
        sa.Column("keywords", sa.String(500), nullable=False,
                  server_default=""),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("category", sa.String(100), nullable=False,
                  server_default="General"),
        sa.Column("active", sa.Boolean, nullable=False,
                  server_default=sa.true()),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_table(
        "knowledge_misses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("normalized", sa.String(500), nullable=False),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("times_asked", sa.Integer, nullable=False,
                  server_default="1"),
        sa.Column("last_asked_by", sa.String(255), nullable=True),
        sa.Column("first_asked_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("last_asked_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "normalized",
                            name="uq_knowledge_miss_question"),
    )

    bind = op.get_bind()
    workspaces = [r[0] for r in bind.execute(
        sa.text("SELECT id FROM workspaces"))]
    table = sa.table(
        "knowledge_entries",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("workspace_id", UUID(as_uuid=True)),
        sa.column("category", sa.String), sa.column("question", sa.String),
        sa.column("phrasings", sa.Text), sa.column("keywords", sa.String),
        sa.column("answer", sa.Text), sa.column("updated_by", sa.String))
    rows = [{"id": uuid.uuid4(), "workspace_id": w, "category": c,
             "question": q, "phrasings": p, "keywords": k, "answer": a,
             "updated_by": "starting set (No. 116)"}
            for w in workspaces for c, q, p, k, a in START]
    if rows:
        op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_table("knowledge_misses")
    op.drop_table("knowledge_entries")
