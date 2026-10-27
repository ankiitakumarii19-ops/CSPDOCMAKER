"""Context and harness: in the Knowledge Base and on Data quality (No. 149).

The new Knowledge Base answers must be reached by the way people ask, and
must not take over a question the starting set (No. 116) already answers.
The harness rows must say where each check stands, from real records.
"""

import importlib.util
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.services import field_quality as fq
from app.services import knowledge_service
from tests.test_field_quality import _auth, _engine, _filled, qdb  # noqa: F401
from tests.test_knowledge_start import ENTRIES as OLD_ENTRIES

on_loop = pytest.mark.asyncio(loop_scope="session")

_MIGRATION = os.path.join(os.path.dirname(__file__), "..", "alembic",
                          "versions", "b3e5f7a9c1d2_knowledge_context_harness.py")


def _load():
    spec = importlib.util.spec_from_file_location("kb_quality", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _load()
NEW = [SimpleNamespace(category=MIGRATION.CATEGORY, question=q, phrasings=p,
                       keywords=k, answer=a) for q, p, k, a in MIGRATION.START]
ALL = OLD_ENTRIES + NEW


@pytest.mark.parametrize("asked,expected", [
    ("what does the app read", "What does the app read? (context)"),
    ("data kahan se aata hai", "What does the app read? (context)"),
    ("what is the context", "What does the app read? (context)"),
    ("what is the harness", "How does the app check itself? (harness)"),
    ("how does the app check its work", "How does the app check itself? (harness)"),
    ("what does the red chip mean", "What do the coloured sheet chips at the top mean?"),
    ("sheet stuck", "What do the coloured sheet chips at the top mean?"),
    ("AO is wrong how to correct", "How do I confirm or correct a value the app filled in?"),
    ("value galat hai", "How do I confirm or correct a value the app filled in?"),
    ("where did this value come from", "Where did this value come from?"),
    ("yeh value kahan se aayi", "Where did this value come from?"),
    ("what are golden cases", "What are the golden cases?"),
])
def test_the_new_answers_are_found(asked, expected):
    [best, *_] = knowledge_service.rank(asked, ALL)
    assert best.entry.question == expected, (asked, best.entry.question,
                                             round(best.score, 2))
    assert best.score >= knowledge_service.ANSWER_AT, (asked, best.score)


@pytest.mark.parametrize("asked,expected", [
    ("how often is the sheet read", "How often is the Google Sheet read?"),
    ("what is bcp", "What is a BCP?"),
    ("which documents are made", "Which documents does the app make?"),
    ("why is my request pending", "Why is a document request pending?"),
    ("whatsapp late kyun aata hai", "Why is a WhatsApp message late or not received?"),
    ("is this chat AI?", "How does this chat work?"),
    ("what does RBO mean", "What are RBO, LHO and AO?"),
])
def test_the_existing_answers_keep_their_questions(asked, expected):
    [best, *_] = knowledge_service.rank(asked, ALL)
    assert best.entry.question == expected, (asked, best.entry.question)


def test_the_answers_name_where_to_look_and_hold_no_contact_details():
    import re
    for e in NEW:
        assert len(e.question) <= 300 and len(e.keywords) <= 500
        assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", e.answer), e.question
        assert not re.search(r"\b\d{10}\b", e.answer), e.question


def test_every_workspace_gets_the_entries_once_and_keeps_its_own(qdb):
    """Runs this migration's downgrade and upgrade on the test database:
    every workspace gets each answer once, and an answer a workspace
    already wrote itself (same question) is neither doubled nor replaced."""
    import subprocess
    import sys
    from tests.conftest import BACKEND_DIR, DEFAULT_WORKSPACE_ID

    def alembic(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args],
                       cwd=BACKEND_DIR, check=True, capture_output=True)

    alembic("downgrade", MIGRATION.down_revision)
    try:
        qdb.execute(text("DELETE FROM knowledge_entries WHERE question = :q"),
                    {"q": "What are the golden cases?"})
        qdb.execute(text(
            "INSERT INTO knowledge_entries (id, workspace_id, question, "
            "phrasings, keywords, answer, category, active, updated_by) "
            "VALUES (gen_random_uuid(), :w, 'What are the golden cases?', "
            "'', '', 'Our own answer', 'Mine', true, 'admin')"),
            {"w": str(DEFAULT_WORKSPACE_ID)})
        qdb.commit()
    finally:
        alembic("upgrade", "head")

    rows = qdb.execute(text(
        "SELECT workspace_id, question, count(*) FROM knowledge_entries "
        "GROUP BY workspace_id, question")).all()
    workspaces = {w for (w,) in qdb.execute(text("SELECT id FROM workspaces"))}
    for question, *_ in MIGRATION.START:
        have = {w for w, q, n in rows if q == question}
        assert have == workspaces, question
    assert all(n == 1 for w, q, n in rows
               if q in {q for q, *_ in MIGRATION.START}), "never twice"
    kept = qdb.execute(text(
        "SELECT answer, updated_by FROM knowledge_entries WHERE workspace_id = "
        ":w AND question = 'What are the golden cases?'"),
        {"w": str(DEFAULT_WORKSPACE_ID)}).one()
    assert tuple(kept) == ("Our own answer", "admin"), "not replaced"


# ---- the harness rows ---------------------------------------------------

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
SETTINGS = SimpleNamespace(csp_sync_interval_minutes=1,
                           google_sheets_sync_interval_minutes=15,
                           source_sheets_interval_minutes=5,
                           calling_sheet_id="", lead_sheet_id="")


def _rows(db):
    db.execute(text("TRUNCATE whatsapp_messages, email_messages, "
                    "knowledge_misses, quality_suggestions, contact_fixes, "
                    "csp_replies, csp_feedback "
                    "RESTART IDENTITY CASCADE"))
    db.commit()
    return {r["key"]: r for r in fq.harness(db, SETTINGS, now=NOW)}


def test_with_nothing_recorded_the_harness_says_so(qdb):
    rows = _rows(qdb)
    assert list(rows) == ["auto_fill", "corrections", "kept_rate", "checked",
                          "freshness", "sending", "mapping_loop",
                          "contact_loop", "csp_replies", "feedback", "chat",
                          "golden", "tests"]
    assert rows["mapping_loop"]["state"] == rows["contact_loop"]["state"] == "empty"
    assert rows["auto_fill"]["state"] == "empty"
    assert rows["kept_rate"]["now"] == "no data yet"
    assert rows["sending"]["state"] == "ok"
    assert rows["chat"] == {**rows["chat"], "now": "none", "state": "ok"}
    assert rows["golden"]["now"] == "60 cases in this version"
    assert rows["golden"]["state"] == rows["tests"]["state"] == "laptop"
    assert rows["freshness"]["state"] == "attention", "nothing read yet"


def test_the_harness_counts_fills_checks_and_the_kept_rate(qdb):
    for code in ("1A994001", "1A994002", "1A994003", "1A994004"):
        _filled(qdb, code, ao=("AO NASHIK", "info"))
    fq.record_check(qdb, "1A994003", {"ao": "AO NASHIK"}, "csp_form", "CSP")
    fq.record_check(qdb, "1A994004", {"ao": "AO PUNE"}, "csp_form", "CSP")
    qdb.commit()
    rows = _rows(qdb)
    assert rows["auto_fill"]["now"].startswith("4 values in use")
    assert rows["corrections"]["now"].startswith("1 corrections")
    assert (rows["kept_rate"]["now"], rows["kept_rate"]["state"]) == ("75.0%", "ok")
    assert rows["checked"]["now"] == "2 of 4 (50.0%)"


def test_a_kept_rate_below_target_needs_a_look(qdb):
    _filled(qdb, "1A994005", ao=("AO NASHIK", "info"))
    fq.record_check(qdb, "1A994005", {"ao": "AO PUNE"}, "csp_form", "CSP")
    qdb.commit()
    assert _rows(qdb)["kept_rate"]["state"] == "attention"


def test_sending_failures_and_chat_misses_are_counted(qdb):
    from app.models.email_message import EmailMessage
    from app.models.knowledge import KnowledgeMiss
    from app.models.whatsapp_message import WhatsAppMessage
    rows = _rows(qdb)    # empties the tables first
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    qdb.add(WhatsAppMessage(csp_id="1A994006", phone="919812345670",
                            kind="data_request", source="test",
                            send_status="failed",
                            send_error="WhatsApp platform unreachable",
                            sent_at=recent))
    qdb.add(EmailMessage(csp_id="1A994006", to_email="x@example.com",
                         kind="documents", subject="s", track_token="t1",
                         send_status="sent", sent_at=recent,
                         bounced_at=recent, bounce_reason="address not found"))
    qdb.add(KnowledgeMiss(normalized="cricket", question="cricket score",
                          times_asked=2, last_asked_at=recent))
    qdb.commit()
    rows = {r["key"]: r for r in fq.harness(qdb, SETTINGS)}
    assert rows["sending"]["now"] == ("WhatsApp: 1 not sent, 0 not received · "
                                      "Email: 0 failed, 1 bounced")
    assert rows["sending"]["state"] == "attention"
    assert rows["chat"]["now"].startswith("1 different questions")
    assert rows["chat"]["state"] == "attention"


@on_loop
async def test_the_harness_is_for_admins(client, qdb):
    r = await client.get("/api/admin/quality/harness", headers=_auth("rm"))
    assert r.status_code == 403
    r = await client.get("/api/admin/quality/harness", headers=_auth("admin"))
    assert r.status_code == 200, r.text
    assert [c["key"] for c in r.json()["checks"]][0] == "auto_fill"
