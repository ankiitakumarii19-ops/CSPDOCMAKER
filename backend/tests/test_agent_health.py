# -*- coding: utf-8 -*-
"""Agent health (No. 252): metrics, issues, history, improving itself.

Every agent (six background agents + the chat) is measured from what it
already records; issues open, stay and resolve; one history row per agent
per day; the agents learn safe lessons by themselves (each undoable) and
propose the rest; issues reach the alert emails; a daily summary.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text

from app.models.agent import (
    ACCEPTED, FAILED, INFORMATIONAL, OK, PROPOSED as F_PROPOSED, REJECTED,
    AgentFinding, AgentRun, AgentState,
)
from app.models.agent_eval import (
    APPLIED, CHAT, CLOSED, CRITICAL, DISMISSED, OPEN, PROPOSED, RESOLVED,
    UNDONE, WARNING, AgentEvalIssue, AgentEvalSnapshot, AgentImprovement,
    AssistantTurn,
)
from app.models.audit_log import AuditLog
from app.models.enums import UserRole
from app.models.knowledge import KnowledgeEntry, KnowledgeMiss
from app.models.workspace_member import WorkspaceMember
from app.services import agent_eval as ev
from app.services import agent_runner as runner
from app.services import agents as _impl  # noqa: F401  (registers the work)
from app.services import alerts, knowledge_service
from app.services.agent_runner import Finding, Outcome
from tests.conftest import DEFAULT_WORKSPACE_ID
from tests.test_field_quality import _engine, qdb  # noqa: F401

NOW = datetime.now(timezone.utc)
KEYS = [a["key"] for a in ev.agents()]


@pytest.fixture
def db(qdb):
    qdb.execute(text(
        "TRUNCATE agent_eval_snapshots, agent_eval_issues, agent_improvements,"
        " assistant_turns, agent_findings, agent_runs, agent_states,"
        " knowledge_entries, knowledge_misses, audit_logs, workspace_members"
        " RESTART IDENTITY CASCADE"))
    qdb.commit()
    # Every background agent ran a moment ago and is fine, unless a test
    # says otherwise.
    for key in KEYS:
        if key != CHAT:
            qdb.add(AgentState(agent_key=key, enabled=True, last_run_at=NOW,
                               consecutive_failures=0))
    qdb.commit()
    return qdb


def S(**over):
    base = dict(alert_agent_failures=3, agent_eval_min_success=90,
                agent_eval_min_result=80, agent_eval_min_chat=70,
                agent_eval_min_acceptance=50, agent_eval_auto_improve=True)
    base.update(over)
    return SimpleNamespace(**base)


def _runs(db, key, ok=0, failed=0, ms=100, at=NOW):
    for i in range(ok):
        db.add(AgentRun(agent_key=key, status=OK, summary="", duration_ms=ms,
                        started_at=at - timedelta(minutes=i + 1)))
    for i in range(failed):
        db.add(AgentRun(agent_key=key, status=FAILED, summary="x",
                        started_at=at - timedelta(minutes=i + 1)))
    db.commit()


def _m(db, key):
    return next(m for m in ev.measure(db, NOW) if m["key"] == key)


def _checks(db, key, **over):
    return {c["check"]: c for c in ev.checks(_m(db, key), S(**over))}


# ---- measuring ------------------------------------------------------------------

def test_every_agent_and_the_chat_are_measured(db):
    assert KEYS[-1] == CHAT and len(KEYS) == 7
    assert {m["key"] for m in ev.measure(db, NOW)} == set(KEYS)


def test_a_finding_kind_ignores_numbers_and_names():
    assert ev.finding_kind("12 record(s) belong to no RM") == \
        ev.finding_kind("7 record(s) belong to no RM")
    assert ev.finding_kind("Data source 'CSP' last failed") == \
        ev.finding_kind("Data source 'INFO' last failed")


def test_reliability_schedule_and_speed(db):
    _runs(db, "monitoring", ok=9, failed=1, ms=200)
    m = _m(db, "monitoring")
    r = m["run"]
    assert (r["ok"], r["failed"], r["success_rate"]) == (9, 1, 90.0)
    assert r["expected_runs"] == 144            # every 10 minutes for a day
    assert r["on_schedule"] == round(100 * 10 / 144, 1)
    assert r["p50_ms"] == 200 and r["p95_ms"] == 200


def test_the_chat_is_scored_on_questions_answered(db):
    for answered in (True, True, True, False):
        db.add(AssistantTurn(asked_by="a@x", kind="knowledge" if answered
                             else "unknown", answered=answered,
                             normalized="x", question="x", duration_ms=50))
    db.commit()
    m = _m(db, CHAT)
    assert m["result"]["rate"] == 75.0 and m["result"]["total"] == 4
    assert m["score"] == 75


def test_a_switched_off_agent_is_not_judged(db):
    db.execute(text("UPDATE agent_states SET enabled=false, "
                    "consecutive_failures=9 WHERE agent_key='data'"))
    db.commit()
    m = _m(db, "data")
    assert m["score"] is None and ev.checks(m, S()) == []
    assert ev.status_of(m, []) == "off"


# ---- issues -----------------------------------------------------------------------

def test_failing_low_success_and_overdue(db):
    _runs(db, "document", ok=8, failed=2)
    db.execute(text("UPDATE agent_states SET consecutive_failures=4, "
                    "last_run_at=now() - interval '3 hours' "
                    "WHERE agent_key='document'"))
    db.commit()
    found = _checks(db, "document")
    assert found["failing"]["severity"] == CRITICAL
    assert found["low_success"]["severity"] == WARNING     # 80% vs bar 90
    _runs(db, "document", failed=8)                         # 8 of 18: critical
    assert _checks(db, "document")["low_success"]["severity"] == CRITICAL
    assert found["overdue"]["severity"] == CRITICAL        # every 3 min
    assert "hours" in found["overdue"]["title"]


def test_slow_against_its_own_normal(db):
    for back in range(1, 6):
        db.add(AgentEvalSnapshot(agent_key="data",
                                 day=ev._today(NOW) - timedelta(days=back),
                                 score=100, metrics={"p95_ms": 2000}))
    db.commit()
    _runs(db, "data", ok=5, ms=30_000)
    m = _m(db, "data")
    assert m["baseline_p95_ms"] == 2000
    assert "slow" in {c["check"] for c in ev.checks(m, S())}


def test_poor_acceptance_and_waiting_proposals(db):
    run = AgentRun(agent_key="setup", status=OK, summary="")
    db.add(run)
    db.flush()
    for i in range(6):
        db.add(AgentFinding(run_id=run.id, agent_key="setup", severity="info",
                            status=REJECTED if i else ACCEPTED,
                            title="map it", decided_at=NOW))
    db.add(AgentFinding(run_id=run.id, agent_key="setup", severity="info",
                        status=F_PROPOSED, title="old one",
                        created_at=NOW - timedelta(days=5)))
    db.commit()
    found = _checks(db, "setup")
    assert found["low_acceptance"]["value"] == round(100 / 6, 1)
    assert "backlog" in found


def test_an_issue_opens_once_stays_and_resolves_with_history(db):
    _runs(db, "verification", ok=1, failed=4)
    first = ev.evaluate(db, NOW)
    assert first["issues"]["opened"] >= 1
    again = ev.evaluate(db, NOW + timedelta(minutes=15))
    assert again["issues"]["opened"] == 0
    rows = db.execute(select(AgentEvalIssue).where(
        AgentEvalIssue.agent_key == "verification")).scalars().all()
    assert len(rows) == 1 and rows[0].status == OPEN

    db.execute(text("DELETE FROM agent_runs"))
    db.commit()
    _runs(db, "verification", ok=5, at=NOW + timedelta(hours=25))
    ev.evaluate(db, NOW + timedelta(hours=25))
    db.expire_all()
    row = db.execute(select(AgentEvalIssue).where(
        AgentEvalIssue.agent_key == "verification",
        AgentEvalIssue.check_key == "low_success")).scalar_one()
    assert row.status == RESOLVED and row.resolved_at is not None


def test_one_history_row_per_agent_per_day(db):
    ev.evaluate(db, NOW)
    ev.evaluate(db, NOW + timedelta(seconds=30))
    n = db.execute(select(func.count()).select_from(AgentEvalSnapshot)).scalar()
    assert n == len(KEYS)
    assert {r["agent"] for r in ev.history(db, 7, now=NOW)} == set(KEYS)


def test_open_issues_reach_the_alert_emails_but_failing_only_once(db):
    db.add(AgentEvalIssue(agent_key="data", check_key="low_result",
                          severity=WARNING, title="Data Agent: poor",
                          detail="d"))
    db.add(AgentEvalIssue(agent_key="data", check_key="failing",
                          severity=CRITICAL, title="Data Agent: failing",
                          detail="d"))
    db.commit()
    keys = {p.key for p in alerts.problems(db, SimpleNamespace(
        alert_agent_failures=99, alert_whatsapp_failures=99,
        csp_sync_interval_minutes=1, google_sheets_sync_interval_minutes=15,
        source_sheets_interval_minutes=15, calling_sheet_id="",
        lead_sheet_id="", backup_status_file=""), NOW)}
    assert "agent_eval:data:low_result" in keys
    assert "agent_eval:data:failing" not in keys


# ---- improving itself ------------------------------------------------------------------

def _rejected(db, n, title="Map 3 placeholder(s) in 'ID'"):
    run = AgentRun(agent_key="setup", status=OK, summary="")
    db.add(run)
    db.flush()
    for _ in range(n):
        db.add(AgentFinding(run_id=run.id, agent_key="setup", severity="info",
                            status=REJECTED, title=title, decided_at=NOW,
                            proposal={"action": "map_placeholders"}))
    db.commit()


def test_it_stops_asking_what_people_always_turn_down(db, monkeypatch):
    _rejected(db, 3)
    lessons = ev.learn(db, S(), NOW)
    db.commit()
    assert lessons["applied"] == 1
    imp = db.execute(select(AgentImprovement)).scalar_one()
    assert (imp.kind, imp.status, imp.automatic) == ("mute_rejected", APPLIED, True)

    def work(_s):
        return Outcome("x", findings=[Finding(
            "Map 5 placeholder(s) in 'BCP'", proposal={"action": "map"})])
    monkeypatch.setitem(runner._WORK, "setup", work)
    run = runner.run(db, "setup")
    f = run.findings[0]
    assert f.status == INFORMATIONAL and f.proposal is None   # still reported
    assert run.detail["quieted"] == 1

    ev.undo(db, imp, "owner@eko.co.in")
    db.commit()
    assert runner.run(db, "setup").findings[0].status == F_PROPOSED
    assert ev.learn(db, S(), NOW)["applied"] == 0   # not learned again


def test_with_self_improving_off_it_only_proposes(db):
    _rejected(db, 4)
    assert ev.learn(db, S(agent_eval_auto_improve=False), NOW)["proposed"] == 1
    db.commit()
    imp = db.execute(select(AgentImprovement)).scalar_one()
    assert imp.status == PROPOSED
    ev.apply(db, imp, "owner@eko.co.in")
    assert imp.status == APPLIED


def test_two_rejections_are_not_enough(db):
    _rejected(db, 2)
    assert ev.learn(db, S(), NOW) == {"applied": 0, "proposed": 0, "closed": 0}


def _kb(db):
    entry = KnowledgeEntry(question="How do I reset my password?",
                           phrasings="", keywords="", answer="Use Forgot password.",
                           category="Help", active=True)
    db.add(entry)
    db.commit()
    return entry


def _turn(db, who, question, at, entry=None):
    db.add(AssistantTurn(
        asked_by=who, kind="knowledge" if entry else "unknown",
        answered=entry is not None, entry_id=entry.id if entry else None,
        normalized=knowledge_service.normalized(question),
        question=question, duration_ms=10, created_at=at))
    db.commit()


def test_the_chat_learns_a_wording_from_a_quick_rephrase(db):
    entry = _kb(db)
    db.add(KnowledgeMiss(normalized=knowledge_service.normalized(
        "password bhool gaya"), question="password bhool gaya", times_asked=1))
    db.commit()
    _turn(db, "a@x", "password bhool gaya", NOW - timedelta(minutes=2))
    _turn(db, "a@x", "how to reset password", NOW - timedelta(minutes=1), entry)

    assert ev.learn(db, S(), NOW)["applied"] == 1
    db.commit()
    db.refresh(entry)
    assert "password bhool gaya" in entry.phrasings
    assert db.execute(select(func.count()).select_from(KnowledgeMiss)).scalar() == 0
    best = knowledge_service.rank("password bhool gaya", [entry])[0]
    assert best.score >= knowledge_service.ANSWER_AT

    imp = db.execute(select(AgentImprovement)).scalar_one()
    ev.undo(db, imp, "owner@eko.co.in")
    db.commit()
    db.refresh(entry)
    assert "bhool" not in entry.phrasings and imp.status == UNDONE


@pytest.mark.parametrize("second_who,second_q,gap", [
    ("b@x", "how to reset password", 1),     # someone else
    ("a@x", "how to reset password", 10),    # too long after
    ("a@x", "reset my login", 1),            # shares no word: a new topic
])
def test_the_chat_does_not_learn_from_unrelated_questions(db, second_who,
                                                          second_q, gap):
    entry = _kb(db)
    _turn(db, "a@x", "password bhool gaya", NOW - timedelta(minutes=gap + 1))
    _turn(db, second_who, second_q, NOW - timedelta(minutes=1), entry)
    assert ev.learn(db, S(), NOW)["applied"] == 0


def test_an_often_unanswered_question_is_proposed_and_closes_itself(db):
    miss = KnowledgeMiss(normalized="gst invoice", question="GST invoice?",
                         times_asked=3)
    db.add(miss)
    db.commit()
    assert ev.learn(db, S(), NOW)["proposed"] == 1
    db.commit()
    imp = db.execute(select(AgentImprovement)).scalar_one()
    assert imp.kind == "kb_entry" and imp.status == PROPOSED
    with pytest.raises(ev.ImprovementError):
        ev.apply(db, imp, "owner")              # written in the Knowledge Base
    assert ev.learn(db, S(), NOW)["proposed"] == 0      # not twice
    db.delete(miss)                                    # an answer was added
    db.commit()
    assert ev.learn(db, S(), NOW)["closed"] == 1
    db.commit()
    assert imp.status == CLOSED


def test_an_agent_that_keeps_failing_is_proposed_off_with_undo(db):
    db.execute(text("UPDATE agent_states SET consecutive_failures=6 "
                    "WHERE agent_key='communication'"))
    db.commit()
    assert ev.learn(db, S(), NOW)["proposed"] == 1
    db.commit()
    imp = db.execute(select(AgentImprovement)).scalar_one()
    ev.apply(db, imp, "owner@eko.co.in")
    db.commit()
    state = db.execute(select(AgentState).where(
        AgentState.agent_key == "communication")).scalar_one()
    assert state.enabled is False
    ev.undo(db, imp, "owner@eko.co.in")
    db.commit()
    assert state.enabled is True
    assert db.execute(select(func.count()).select_from(AuditLog).where(
        AuditLog.resource_type == "agent_improvement")).scalar() == 2


def test_a_dismissed_proposal_is_not_asked_again(db):
    db.add(KnowledgeMiss(normalized="gst", question="GST?", times_asked=5))
    db.commit()
    ev.learn(db, S(), NOW)
    db.commit()
    ev.dismiss(db, db.execute(select(AgentImprovement)).scalar_one(), "owner")
    db.commit()
    assert ev.learn(db, S(), NOW)["proposed"] == 0
    assert db.execute(select(AgentImprovement)).scalar_one().status == DISMISSED


# ---- the daily summary -------------------------------------------------------------------

def test_the_daily_summary_once_a_day_to_the_super_admins(db, monkeypatch):
    from app.config import get_settings
    from app.services import message_sender
    db.add(WorkspaceMember(workspace_id=DEFAULT_WORKSPACE_ID,
                           email="owner@eko.co.in", role=UserRole.SUPER_ADMIN,
                           active=True))
    db.commit()
    s = get_settings()
    monkeypatch.setattr(s, "test_copy", False)
    monkeypatch.setattr(s, "agent_eval_summary_on", True)
    monkeypatch.setattr(s, "agent_eval_summary_hour", 0)
    monkeypatch.setattr(s, "alert_to", "")
    monkeypatch.setattr(message_sender, "link_is_reachable", lambda url: True)
    sent = []
    out = ev.run_summary(db, NOW, send=lambda to, subj, body: (
        sent.append((to, subj, body)) or (True, "")))
    assert out["sent_to"] == ["owner@eko.co.in"]
    assert "agent health" in sent[0][1] and "Chat assistant" in sent[0][2]
    assert ev.run_summary(db, NOW + timedelta(minutes=5),
                          send=lambda *a: (True, ""))["skipped"] == \
        "already sent today"


def test_the_laptop_sends_no_summary(db, monkeypatch):
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "link_is_reachable", lambda url: False)
    assert "not the server" in ev.run_summary(db, NOW)["skipped"]
