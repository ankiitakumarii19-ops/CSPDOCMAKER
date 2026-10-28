"""Feedback answer 2 also gets the data verification link (No. 163):
the migration updates the starting wording (not an Admin's own) and the
answer-2 replies still waiting. Nothing is sent by it.
"""

import subprocess
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.knowledge import KnowledgeEntry
from app.services import csp_replies as cr
from tests.conftest import BACKEND_DIR
from tests.test_csp_replies import rdb  # noqa: F401
from tests.test_field_quality import _engine, qdb  # noqa: F401

MIGRATION = "e5b7d9f1a3c4"
QUESTION = "CSP reply: feedback \u2014 did not get them"


def _alembic(*args):
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR,
                   check=True, capture_output=True)


def _entry(db, answer):
    import importlib.util
    import os
    path = os.path.join(BACKEND_DIR, "alembic", "versions",
                        "e5b7d9f1a3c4_feedback_2_gets_the_link.py")
    spec = importlib.util.spec_from_file_location("feedback_2_link", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    db.add(KnowledgeEntry(question=QUESTION, phrasings="", keywords="",
                          answer=answer if answer is not None else m.OLD,
                          category="CSP replies", active=True, updated_by=m.BY))


def _reply(db, code, status, intents, action):
    db.add(cr.CspReply(csp_id=code, phone="919800000000", messages=[],
                       last_in_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
                       intents=intents, status=status, action=action))


def test_the_migration_adds_the_link_to_answer_2(rdb):
    _alembic("downgrade", "d7f9b3c5e1a8")
    try:
        _entry(rdb, None)
        _reply(rdb, "1A996001", "draft", ["feedback_2"], "resend_documents")
        _reply(rdb, "1A996002", "sent", ["feedback_2"], "resend_documents")
        _reply(rdb, "1A996003", "draft", ["feedback_3"], "fresh_link")
        rdb.commit()
    finally:
        _alembic("upgrade", "head")
    rdb.expire_all()
    entry = rdb.execute(select(KnowledgeEntry).where(
        KnowledgeEntry.question == QUESTION)).scalars().first()
    assert "data verification ka link" in entry.answer
    got = {r.csp_id: r.action for r in rdb.execute(select(cr.CspReply)).scalars()}
    assert got == {"1A996001": "resend_documents,fresh_link",
                   "1A996002": "resend_documents",       # already sent: the button
                   "1A996003": "fresh_link"}


def test_an_admins_own_wording_is_kept(rdb):
    _alembic("downgrade", "d7f9b3c5e1a8")
    try:
        _entry(rdb, "Apna email dekhiye.")
        rdb.commit()
    finally:
        _alembic("upgrade", "head")
    rdb.expire_all()
    assert rdb.execute(select(KnowledgeEntry.answer).where(
        KnowledgeEntry.question == QUESTION)).scalars().first() == "Apna email dekhiye."
