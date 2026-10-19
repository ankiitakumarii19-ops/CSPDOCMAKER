"""The Knowledge Base's starting set answers the way people ask (No. 116).

The entries the migration writes are matched against everyday questions in
English, Hinglish and Hindi; each must reach the intended entry, and nothing
unrelated may get an answer. No database: the matcher is pure.
"""

import importlib.util
import os
from types import SimpleNamespace

import pytest

from app.services import knowledge_service

_MIGRATION = os.path.join(os.path.dirname(__file__), "..", "alembic",
                          "versions", "e8a0c2d4f6b9_knowledge_base.py")


def _start_entries():
    spec = importlib.util.spec_from_file_location("kb_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [SimpleNamespace(category=c, question=q, phrasings=p, keywords=k,
                            answer=a)
            for c, q, p, k, a in module.START]


ENTRIES = _start_entries()


@pytest.mark.parametrize("asked,expected", [
    ("what is bcp", "What is a BCP?"),
    ("BCP kya hai?", "What is a BCP?"),
    ("difference between KO and Sub-KO", "What is a KO and a Sub-KO?"),
    ("which documents are made", "Which documents does the app make?"),
    ("why is my request pending", "Why is a document request pending?"),
    ("documents pending kyun hai", "Why is a document request pending?"),
    ("what is the photo size", "What size is the photo on the documents?"),
    ("passport photo size", "What size is the photo on the documents?"),
    ("who can login", "Who can log in to the app?"),
    ("I didn't get the OTP", "I did not get the login code"),
    ("code nahi aaya", "I did not get the login code"),
    ("how long does the session last", "How long does a sign-in last?"),
    ("what date is on the certificate", "What date is printed on the certificates?"),
    ("where are documents stored", "Where are the documents stored?"),
    ("is this chat AI?", "How does this chat work?"),
    ("what does RBO mean", "What are RBO, LHO and AO?"),
    ("how to add an answer to the knowledge base", "How do I add an answer to the chat?"),
    ("whatsapp late kyun aata hai", "Why is a WhatsApp message late or not received?"),
    ("what can an admin do", "What can an Admin do?"),
    ("what is a csp", "What is a CSP?"),
    ("how often is the sheet read", "How often is the Google Sheet read?"),
])
def test_everyday_questions_reach_the_right_entry(asked, expected):
    [best, *_] = knowledge_service.rank(asked, ENTRIES)
    assert best.entry.question == expected, (asked, best.entry.question,
                                             round(best.score, 2))
    assert best.score >= knowledge_service.ANSWER_AT, (asked, best.score)


@pytest.mark.parametrize("asked", [
    "what is the weather tomorrow",
    "book a train ticket to Delhi",
    "cricket score",
])
def test_unrelated_questions_get_no_answer(asked):
    ranked = knowledge_service.rank(asked, ENTRIES)
    assert not ranked or ranked[0].score < knowledge_service.ANSWER_AT, \
        (asked, ranked[0].entry.question, ranked[0].score)


def test_matching_is_deterministic():
    first = [(m.entry.question, m.score)
             for m in knowledge_service.rank("documents pending", ENTRIES)]
    for _ in range(5):
        assert [(m.entry.question, m.score) for m in knowledge_service.rank(
            "documents pending", ENTRIES)] == first


def test_every_starting_answer_is_reachable_by_its_own_question():
    for e in ENTRIES:
        [best, *_] = knowledge_service.rank(e.question, ENTRIES)
        assert best.entry is e, (e.question, best.entry.question)
