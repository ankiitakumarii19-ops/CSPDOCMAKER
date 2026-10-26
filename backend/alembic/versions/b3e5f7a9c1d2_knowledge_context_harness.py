"""Knowledge Base: the context and the harness (No. 149)

26 Oct 2026: "both [the context table and the harness table] have to be in
the Knowledge Base." Adds a "Data quality" set of answers to every existing
workspace: what the app reads, how it checks itself, the freshness chips,
confirming / correcting a filled value, where a value came from, the golden
cases. They are ordinary entries — Admins and Super Admins see and edit them
on Admin -> Knowledge Base, and the chat answers from them. The live state
of each is on Admin -> Setup -> Data quality.

An entry whose question a workspace already has is not added twice.
Downgrade removes only these entries, and only while still as written here.

Revision ID: b3e5f7a9c1d2
Revises: a7d2c4e6f8b1
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "b3e5f7a9c1d2"
down_revision = "a7d2c4e6f8b1"
branch_labels = None
depends_on = None

BY = "starting set (No. 149)"
CATEGORY = "Data quality"

# (question, other phrasings, keywords, answer)
START = [
    ("What does the app read? (context)",
     "which sheets does the app read\nwhere does the data come from\n"
     "what is the context\ndata kahan se aata hai\n"
     "kaun si sheet padhi jaati hai\ndata sources",
     "context, sources, data source, sheets read",
     "Everything the app decides is made from these:\n"
     "- **CSP sheet** (KOData, SUBKOData) — every CSP's details; read about "
     "every minute. The sheet is always taken as correct.\n"
     "- **INFO tab** (in the CSP sheet) — fills blank AO, RBO, DC, ASM, LHO, "
     "State and RM, by branch, district or territory.\n"
     "- **Sign-in list** (Authorization sheet) — who may sign in and as "
     "which role; read every 15 minutes.\n"
     "- **Calling & Lead sheets** — old CSPs (Calling sheet), new ones "
     "going live (Lead raw data) and holds; read every 5 minutes.\n"
     "- **Address tab** — addresses of old CSPs (temporary).\n"
     "- **Zoho Lead** — fills a blank email, address, state or gender "
     "before a CSP is asked.\n"
     "When each was last read, and whether that is on time: **Admin → "
     "Setup → Data quality → Context**, and the coloured chips at the top "
     "of every screen."),
    ("How does the app check itself? (harness)",
     "what is the harness\nhow does the app check its work\n"
     "quality checks\napp apni galti kaise pakadta hai\nself check",
     "harness, checks, quality checks, self check",
     "- **Auto-fill record** — every value the app fills in by itself is "
     "saved with why it was chosen.\n"
     "- **Corrections log** — every change a person makes to such a value "
     "(CSP's form, sheet editor, Google Sheet, Data quality page), with who, "
     "where and how many characters changed.\n"
     "- **Kept rate** — share of filled values nobody had to correct; "
     "target above 75%.\n"
     "- **Checked by a person** — values someone confirmed or corrected.\n"
     "- **Freshness watch** — whether every sheet is read on time, late or "
     "stuck.\n"
     "- **Sending failures** — WhatsApp messages and emails that did not "
     "go or did not arrive, each with its reason.\n"
     "- **Unanswered chat questions** — so an Admin can add the answer here.\n"
     "- **Golden cases** and **automatic tests** — run on the laptop before "
     "every push; a failure stops the deploy.\n"
     "Where each stands now: **Admin → Setup → Data quality → Harness**."),
    ("What do the coloured sheet chips at the top mean?",
     "green chip\nred chip\nsync status\nsheet stuck\nchip ka matlab\n"
     "csp sheet just now",
     "chip, chips, freshness, stuck, late",
     "Each chip is a sheet the app reads and when it was last read in "
     "full:\n- **Green** — on time\n- **Amber** — late (missed about 3 "
     "reads)\n- **Red** — the last read failed, or reads start but never "
     "finish (stuck)\n- **Grey** — never read yet\n"
     "Hover a chip for details. Admins see the reason for a failure on "
     "Admin → Setup → Data quality."),
    ("How do I confirm or correct a value the app filled in?",
     "correct ao\nwrong ao\nauto filled value wrong\nconfirm value\n"
     "value galat hai\nfix wrong rbo",
     "confirm, correct, auto-filled, wrong value",
     "Admin → Setup → **Data quality** → *Auto-filled values*:\n"
     "- **Confirm** — the value is right; nothing is written.\n"
     "- **Correct** — type the right value and **Save to sheet**; it is "
     "written to the CSP sheet (like the sheet editor) and used the next "
     "time that CSP's documents are made. Nothing is sent to anyone.\n"
     "The RM name is changed in the CSP sheet itself, because it decides "
     "who owns the CSP."),
    ("Where did this value come from?",
     "why is the ao this\nwhere does the rbo come from\nsource of value\n"
     "yeh value kahan se aayi\nwhy this value",
     "source, why this value, from info tab",
     "Search the CSP in the admin top bar: under each value the app filled "
     "in by itself there is a note such as *From INFO tab · not checked by "
     "anyone yet* — hover it for the reason (e.g. *by branch VISARWADI*). "
     "Values with no note were typed into the sheet. All of them are listed "
     "on Admin → Setup → Data quality."),
    ("What are the golden cases?",
     "golden test\ngolden cases kya hai\ncheck before push\n"
     "before deploy check",
     "golden, golden cases",
     "60 fixed CSP situations with their right answers — KO / Sub-KO "
     "documents, AO / RBO / DC mapping, RM owner, holds, mobile numbers, "
     "the Zoho address, what a CSP is asked, WhatsApp or email, old vs new. "
     "They are run on the laptop before every push; if one fails the change "
     "does not go to the server. The file is backend/tests/golden/cases.json "
     "(made-up people, real situations)."),
]


def upgrade() -> None:
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
            "SELECT question FROM knowledge_entries WHERE workspace_id = :w"),
            {"w": w})}
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
            "AND updated_by = :by"), {"q": q, "a": a, "by": BY})
