"""
CSP DocMaker — Agent health: how well each agent does its job (No. 252)

Asked 25 Nov 2026: "all eval metrics that can be applied to my agent in a
dashboard; if any issue it should let me know; the history should be there;
and it should improve itself."

The "agents" are the six background agents (agent_registry) and the chat
assistant (key 'chat'). Everything here is counted from what they already
record — runs, findings and decisions, documents, messages, sheet reads,
CSP answers, chat questions. No AI (No. 116): fixed rules only.

1. MEASURE  (per agent; measure())
   Reliability   runs in 24 h; share that worked; runs in a row that failed
   On schedule   runs done / runs due in 24 h; minutes since the last run
   Speed         typical (p50) and slow (p95) run time in 24 h, against the
                 agent's OWN normal - the median of its daily p95 over the
                 last 14 days (learned, not a fixed number)
   Result        each agent's own job over 7 days - documents made without
                 error, messages that went, sheet reads that worked, CSPs
                 who answered their link, records complete, nothing
                 blocking set-up; for the chat: questions answered
   Judgement     proposals accepted / decided over 30 days; proposals
                 waiting and for how long
   Noise         findings per run; findings quieted by an improvement
   -> one score 0-100 (weighted mean of what applies) and a colour.

2. ISSUES  (checks(); update_issues())
   failing, overdue / never ran, low success, slow, poor result, poor
   acceptance, proposals waiting > 3 days. Bars are workspace settings
   (Settings -> Agent health). An issue is opened once, kept up to date while
   it lasts, resolved when it stops; never deleted. Open issues are shown on
   Agent health and in the Admin bell, and emailed to the Super Admins by
   services/alerts.py (once, again every ALERT_REPEAT_HOURS, and "fixed").

3. HISTORY  (save_snapshots(); history())
   One row per agent per day (its numbers and score at the day's last
   check) — the charts, and the agent's own normal for the speed check.

4. IMPROVE ITSELF  (learn())
   By itself (setting agent_eval_auto_improve; each has Undo):
     * mute_rejected - a kind of proposal people turned down 3+ times and
       never accepted (60 days): the agent stops ASKING; it still reports.
     * kb_phrasing - someone's chat question got no answer, and within 3
       minutes the same person asked again in other words and the
       Knowledge Base answered: the first wording is added to that entry
       (they share a word), so the next person is answered first time.
   Proposed (the Super Admin decides):
     * kb_entry - a question nobody can answer, asked 3+ times: write the
       answer (closes by itself once the Knowledge Base answers it).
     * disable_failing - an agent that failed 2 x ALERT_AGENT_FAILURES runs
       in a row: switch it off until fixed (Undo switches it back on).
   Nothing that reaches a CSP, a document or a message is ever changed by
   itself.
"""

import logging
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, select

from app.models.agent import (
    ACCEPTED, FAILED, OK, PROPOSED as FINDING_PROPOSED, REJECTED, SKIPPED,
    AgentFinding, AgentRun, AgentState,
)
from app.models.agent_eval import (
    APPLIED, CHAT, CLOSED, CRITICAL, DISMISSED, OPEN, PROPOSED, RESOLVED,
    UNDONE, WARNING, AgentEvalIssue, AgentEvalSnapshot, AgentImprovement,
    AssistantTurn,
)
from app.services import agent_registry

logger = logging.getLogger(__name__)

DAY = timedelta(hours=24)
WEEK = timedelta(days=7)
MONTH = timedelta(days=30)

# Fixed parts of the rules (the bars people may change are settings).
MIN_RUNS = 3              # runs before "share that worked" is judged
MIN_RESULTS = 5           # results before "result" is judged
MIN_DECISIONS = 5         # decided proposals before "accepted" is judged
SLOW_FLOOR_MS = 10_000    # never "slow" under 10 s
SLOW_TIMES = 3            # p95 at 3 x its own normal = slow
BASELINE_DAYS = 14
BASELINE_MIN_DAYS = 3
BACKLOG_HOURS = 72
OVERDUE_TIMES = 3         # no run for 3 x its interval (at least 30 min)
MUTE_AFTER_REJECTIONS = 3
REPHRASE_MINUTES = 3
KB_ENTRY_AFTER = 3

CHAT_AGENT = {
    "key": CHAT, "name": "Chat assistant",
    "owns": "Does the chat answer what people ask it?",
    "every_minutes": None, "risk": "low",
}

RESULT_LABELS = {
    "setup": "Nothing blocking documents",
    "data": "Records complete",
    "verification": "CSPs who answered their link",
    "document": "Documents made without error",
    "communication": "Messages that went out",
    "monitoring": "Sheet reads that worked",
    CHAT: "Questions answered",
}


# ---- small helpers -----------------------------------------------------------

def finding_kind(title: str) -> str:
    """A finding's kind: its title with names and numbers taken out, so
    "12 record(s) belong to no RM" and "7 record(s) …" are one kind."""
    text = re.sub(r"'[^']*'", "'…'", title or "")
    text = re.sub(r"\d+", "#", text)
    return " ".join(text.split())[:200]


def _rate(good: int, total: int) -> Optional[float]:
    return round(100.0 * good / total, 1) if total else None


def _percentile(values: List[int], share: float) -> Optional[int]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(share * (len(ordered) - 1)))))
    return int(ordered[index])


def _aware(when: Optional[datetime]) -> Optional[datetime]:
    if when is not None and when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when


def _iso(when: Optional[datetime]) -> Optional[str]:
    return when.isoformat() if when else None


def _today(now: datetime) -> date:
    """The workspace's own day (its time zone, Settings -> Sending hours)."""
    from app.workers.verify_old_csps_worker import send_zone
    return now.astimezone(send_zone()).date()


def agents() -> List[dict]:
    """Every agent measured: the six background agents, then the chat."""
    out = []
    for a in agent_registry.all_agents():
        out.append({"key": a.key, "name": a.name, "owns": a.owns,
                    "every_minutes": a.every_minutes
                    if a.trigger != agent_registry.ON_DEMAND else None,
                    "risk": a.risk})
    out.append(dict(CHAT_AGENT))
    return out


def name_of(key: str) -> str:
    for a in agents():
        if a["key"] == key:
            return a["name"]
    return key


# ---- 1. measuring --------------------------------------------------------------

def _states(session) -> Dict[str, AgentState]:
    return {s.agent_key: s for s in session.execute(select(AgentState)).scalars()}


def run_numbers(session, key: str, now: datetime,
                every_minutes: Optional[int], enabled: bool) -> dict:
    """Reliability, schedule, speed and noise over the last 24 hours."""
    since = now - DAY
    rows = session.execute(
        select(AgentRun.status, AgentRun.duration_ms, AgentRun.started_at,
               AgentRun.detail)
        .where(AgentRun.agent_key == key, AgentRun.started_at >= since)
    ).all()
    ok = sum(1 for r in rows if r.status == OK)
    failed = sum(1 for r in rows if r.status == FAILED)
    skipped = sum(1 for r in rows if r.status == SKIPPED)
    durations = [r.duration_ms for r in rows
                 if r.status == OK and r.duration_ms is not None]
    quieted = sum(int((r.detail or {}).get("quieted") or 0) for r in rows)

    expected = None
    on_schedule = None
    if every_minutes and enabled:
        expected = max(1, int(24 * 60 / every_minutes))
        on_schedule = round(min(100.0, 100.0 * (ok + failed) / expected), 1)

    findings = dict(session.execute(
        select(AgentFinding.severity, func.count())
        .where(AgentFinding.agent_key == key, AgentFinding.created_at >= since)
        .group_by(AgentFinding.severity)).all())
    total_findings = sum(findings.values())
    return {
        "runs": ok + failed + skipped, "ok": ok, "failed": failed,
        "skipped": skipped,
        "success_rate": _rate(ok, ok + failed),
        "expected_runs": expected, "on_schedule": on_schedule,
        "p50_ms": _percentile(durations, 0.5),
        "p95_ms": _percentile(durations, 0.95),
        "findings": total_findings,
        "critical": int(findings.get("critical", 0)),
        "warnings": int(findings.get("warning", 0)),
        "findings_per_run": round(total_findings / (ok or 1), 1) if ok else None,
        "quieted": quieted,
    }


def decision_numbers(session, key: str, now: datetime) -> dict:
    """Proposals decided over 30 days, and those still waiting."""
    decided = dict(session.execute(
        select(AgentFinding.status, func.count())
        .where(AgentFinding.agent_key == key,
               AgentFinding.status.in_((ACCEPTED, REJECTED)),
               AgentFinding.decided_at >= now - MONTH)
        .group_by(AgentFinding.status)).all())
    accepted, rejected = int(decided.get(ACCEPTED, 0)), int(decided.get(REJECTED, 0))
    waiting, oldest = session.execute(
        select(func.count(), func.min(AgentFinding.created_at))
        .where(AgentFinding.agent_key == key,
               AgentFinding.status == FINDING_PROPOSED)).one()
    oldest = _aware(oldest)
    return {
        "accepted": accepted, "rejected": rejected,
        "acceptance_rate": _rate(accepted, accepted + rejected),
        "waiting": int(waiting or 0),
        "oldest_waiting_hours": round((now - oldest).total_seconds() / 3600, 1)
        if oldest else None,
    }


def _last_ok_detail(session, key: str, since: datetime) -> Optional[dict]:
    """The newest good run's numbers — only if it ran in the window, so an
    agent that stopped is not judged on what it saw weeks ago."""
    row = session.execute(
        select(AgentRun.detail).where(AgentRun.agent_key == key,
                                      AgentRun.status == OK,
                                      AgentRun.started_at >= since)
        .order_by(AgentRun.started_at.desc()).limit(1)).first()
    return (row[0] or {}) if row else None


def ago(minutes: Optional[int]) -> str:
    """'45 minutes', '5 hours', '3 days'."""
    if minutes is None:
        return "never"
    if minutes < 120:
        return f"{minutes} minutes"
    if minutes < 48 * 60:
        return f"{minutes // 60} hours"
    return f"{minutes // (24 * 60)} days"


def result_numbers(session, key: str, now: datetime) -> dict:
    """The agent's own job, over 7 days: good / total and the share."""
    since = now - WEEK
    good = total = 0
    note = ""
    basis = "over 7 days"
    if key in ("setup", "data"):
        basis = "at the last check"
    if key == "setup":
        detail = _last_ok_detail(session, key, since)
        if detail is not None:
            problems = int(detail.get("problems") or 0)
            good, total = (1 if problems == 0 else 0), 1
            note = (f"{problems} thing(s) need attention at the last check"
                    if problems else "Nothing blocking at the last check")
    elif key == "data":
        detail = _last_ok_detail(session, key, since)
        if detail is not None:
            good, total = int(detail.get("complete") or 0), int(detail.get("total") or 0)
            note = (f"{detail.get('need_csp', 0)} waiting on the CSP, "
                    f"{detail.get('need_rm', 0)} on INFO / the RM")
    elif key == "verification":
        from app.models.data_request import DataRequest
        counts = dict(session.execute(
            select(DataRequest.status, func.count())
            .where(DataRequest.created_at >= since,
                   DataRequest.status.in_(("answered", "expired")))
            .group_by(DataRequest.status)).all())
        good = int(counts.get("answered", 0))
        total = good + int(counts.get("expired", 0))
        unsaved = session.execute(
            select(func.count()).select_from(DataRequest)
            .where(DataRequest.created_at >= since,
                   DataRequest.status == "answered",
                   DataRequest.sheet_error.isnot(None))).scalar() or 0
        note = (f"{unsaved} answer(s) could not be written to the sheet"
                if unsaved else "Every answer reached the sheet")
    elif key == "document":
        from app.models.enums import JobState
        from app.models.processing_job import ProcessingJob
        bad_states = (JobState.FAILED_DOCUMENT_GENERATION,
                      JobState.FAILED_DOCUMENT_VALIDATION,
                      JobState.FAILED_PDF_CONVERSION)
        made_states = (JobState.DOCUMENT_GENERATED, JobState.DOCUMENT_VALIDATING,
                       JobState.DOCUMENT_VALIDATED, JobState.EMAIL_VALIDATING,
                       JobState.EMAIL_VALIDATED, JobState.READY_TO_SEND,
                       JobState.AWAITING_CONFIRMATION, JobState.EMAIL_SENDING,
                       JobState.EMAIL_SENT, JobState.SMS_SENDING,
                       JobState.SMS_SENT, JobState.COMPLETED,
                       JobState.FAILED_EMAIL_VALIDATION,
                       JobState.FAILED_EMAIL_SENDING,
                       JobState.FAILED_SMS_SENDING)
        counts = dict(session.execute(
            select(ProcessingJob.current_state, func.count())
            .where(ProcessingJob.updated_at >= since,
                   ProcessingJob.current_state.in_(bad_states + made_states))
            .group_by(ProcessingJob.current_state)).all())
        bad = sum(int(counts.get(s, 0)) for s in bad_states)
        good = sum(int(counts.get(s, 0)) for s in made_states)
        total = good + bad
        note = f"{bad} failed while being made" if bad else "None failed"
    elif key == "communication":
        from app.models.email_message import FAILED as EMAIL_FAILED, SENT as EMAIL_SENT, EmailMessage
        from app.models.whatsapp_message import SEND_FAILED, SEND_SENT, WhatsAppMessage
        wa = dict(session.execute(
            select(WhatsAppMessage.send_status, func.count())
            .where(WhatsAppMessage.sent_at >= since,
                   WhatsAppMessage.is_test.is_(False),
                   WhatsAppMessage.send_status.in_((SEND_SENT, SEND_FAILED)))
            .group_by(WhatsAppMessage.send_status)).all())
        em = dict(session.execute(
            select(EmailMessage.send_status, func.count())
            .where(EmailMessage.sent_at >= since,
                   EmailMessage.send_status.in_((EMAIL_SENT, EMAIL_FAILED)))
            .group_by(EmailMessage.send_status)).all())
        sent = int(wa.get(SEND_SENT, 0)) + int(em.get(EMAIL_SENT, 0))
        failed = int(wa.get(SEND_FAILED, 0)) + int(em.get(EMAIL_FAILED, 0))
        good, total = sent, sent + failed
        note = (f"WhatsApp {wa.get(SEND_SENT, 0)} went / {wa.get(SEND_FAILED, 0)} "
                f"failed; email {em.get(EMAIL_SENT, 0)} / {em.get(EMAIL_FAILED, 0)}")
    elif key == "monitoring":
        from app.models.sync_run import SyncRun
        counts = dict(session.execute(
            select(SyncRun.status, func.count())
            .where(SyncRun.started_at >= since,
                   SyncRun.status.in_(("completed", "failed")))
            .group_by(SyncRun.status)).all())
        good = int(counts.get("completed", 0))
        total = good + int(counts.get("failed", 0))
        note = f"{total - good} read(s) failed" if total - good else "None failed"
    elif key == CHAT:
        rows = session.execute(
            select(AssistantTurn.answered, AssistantTurn.kind, func.count())
            .where(AssistantTurn.created_at >= since)
            .group_by(AssistantTurn.answered, AssistantTurn.kind)).all()
        total = sum(n for _a, _k, n in rows)
        good = sum(n for a, _k, n in rows if a)
        from_kb = sum(n for _a, k, n in rows if k == "knowledge")
        note = f"{from_kb} from the Knowledge Base, {total - good} not answered"
    return {"label": RESULT_LABELS.get(key, "Result"), "good": good,
            "total": total, "rate": _rate(good, total), "note": note,
            "basis": basis}


def chat_numbers(session, now: datetime) -> dict:
    """The chat's own run numbers: questions in 24 h and how fast."""
    since = now - DAY
    rows = session.execute(
        select(AssistantTurn.answered, AssistantTurn.duration_ms)
        .where(AssistantTurn.created_at >= since)).all()
    durations = [r.duration_ms for r in rows]
    last = session.execute(select(func.max(AssistantTurn.created_at))).scalar()
    return {
        "runs": len(rows), "ok": sum(1 for r in rows if r.answered),
        "failed": 0, "skipped": 0,
        "success_rate": None, "expected_runs": None, "on_schedule": None,
        "p50_ms": _percentile(durations, 0.5),
        "p95_ms": _percentile(durations, 0.95),
        "findings": 0, "critical": 0, "warnings": 0,
        "findings_per_run": None, "quieted": 0,
        "last_question_at": _iso(_aware(last)),
    }


def baseline_p95(session, key: str, today: date) -> Optional[int]:
    """The agent's own normal slow-run time: median of its daily p95 over
    the last 14 days (today left out). None until 3 days are known."""
    rows = session.execute(
        select(AgentEvalSnapshot.metrics)
        .where(AgentEvalSnapshot.agent_key == key,
               AgentEvalSnapshot.day < today,
               AgentEvalSnapshot.day >= today - timedelta(days=BASELINE_DAYS))
    ).scalars().all()
    values = [int(m["p95_ms"]) for m in rows if m and m.get("p95_ms")]
    if len(values) < BASELINE_MIN_DAYS:
        return None
    return int(statistics.median(values))


def score_of(m: dict) -> Optional[int]:
    """0-100: the weighted mean of the parts that apply to this agent."""
    parts: List[Tuple[float, float]] = []
    run = m["run"]
    if run.get("success_rate") is not None:
        parts.append((run["success_rate"], 3))
    if run.get("on_schedule") is not None:
        parts.append((run["on_schedule"], 2))
    if m["result"].get("rate") is not None:
        parts.append((m["result"]["rate"], 3))
    d = m["decisions"]
    if d.get("acceptance_rate") is not None and \
            d["accepted"] + d["rejected"] >= MIN_DECISIONS:
        parts.append((d["acceptance_rate"], 1))
    base, p95 = m.get("baseline_p95_ms"), run.get("p95_ms")
    if base and p95:
        ratio = p95 / base
        speed = 100.0 if ratio <= 1.5 else 50.0 if ratio >= SLOW_TIMES else \
            100.0 - 50.0 * (ratio - 1.5) / (SLOW_TIMES - 1.5)
        parts.append((speed, 1))
    if not parts:
        return None
    return int(round(sum(v * w for v, w in parts) / sum(w for _v, w in parts)))


def measure(session, now: Optional[datetime] = None) -> List[dict]:
    """Every agent's numbers now (no writes)."""
    now = now or datetime.now(timezone.utc)
    today = _today(now)
    states = _states(session)
    out = []
    for a in agents():
        key = a["key"]
        state = states.get(key)
        if key == CHAT:
            enabled = True
            run = chat_numbers(session, now)
            last_run = None
            failures = 0
        else:
            enabled = (state.enabled if state is not None
                       else agent_registry.get(key).enabled_by_default)
            run = run_numbers(session, key, now, a["every_minutes"], enabled)
            last_run = _aware(state.last_run_at) if state else None
            failures = int(state.consecutive_failures or 0) if state else 0
        m = {
            **a, "enabled": enabled,
            "run": run,
            "result": result_numbers(session, key, now),
            "decisions": decision_numbers(session, key, now)
            if key != CHAT else {"accepted": 0, "rejected": 0,
                                 "acceptance_rate": None, "waiting": 0,
                                 "oldest_waiting_hours": None},
            "last_run_at": _iso(last_run),
            "minutes_since_last_run": int((now - last_run).total_seconds() // 60)
            if last_run else None,
            "consecutive_failures": failures,
            "baseline_p95_ms": baseline_p95(session, key, today),
        }
        m["score"] = score_of(m) if enabled else None
        out.append(m)
    return out


# ---- 2. issues -----------------------------------------------------------------

def checks(m: dict, settings) -> List[dict]:
    """What is wrong with one agent now: [{check, severity, title, detail,
    value, limit}]. A switched-off agent is not judged."""
    if not m["enabled"]:
        return []
    name, run, key = m["name"], m["run"], m["key"]
    found = []

    def add(check, severity, title, detail, value=None, limit=None):
        found.append({"check": check, "severity": severity,
                      "title": f"{name}: {title}", "detail": detail,
                      "value": value, "limit": limit})

    if key != CHAT:
        bar = int(settings.alert_agent_failures)
        if m["consecutive_failures"] >= bar:
            add("failing", CRITICAL,
                f"failed {m['consecutive_failures']} runs in a row",
                "Its last runs ended with an error. Agents → its run history "
                "shows the error.", m["consecutive_failures"], bar)

        every = m["every_minutes"]
        if every:
            late_after = max(OVERDUE_TIMES * every, 30)
            since = m["minutes_since_last_run"]
            if since is None:
                add("overdue", WARNING, "has never run",
                    "It is switched on but no run is recorded. Is the "
                    "background worker (and its clock) running?")
            elif since > late_after:
                add("overdue", CRITICAL, f"has not run for {ago(since)}",
                    f"It should run every {every} minutes. Is the background "
                    "worker (and its clock) running?", since, late_after)

        bar = float(settings.agent_eval_min_success)
        if run["ok"] + run["failed"] >= MIN_RUNS and \
                run["success_rate"] is not None and run["success_rate"] < bar:
            add("low_success",
                CRITICAL if run["success_rate"] < bar - 30 else WARNING,
                f"only {run['success_rate']:g}% of runs worked in 24 hours",
                f"{run['failed']} of {run['ok'] + run['failed']} runs failed "
                f"(bar {bar:g}%).", run["success_rate"], bar)

        d = m["decisions"]
        bar = float(settings.agent_eval_min_acceptance)
        if d["accepted"] + d["rejected"] >= MIN_DECISIONS and \
                d["acceptance_rate"] is not None and d["acceptance_rate"] < bar:
            add("low_acceptance", WARNING,
                f"only {d['acceptance_rate']:g}% of its proposals were accepted",
                f"{d['rejected']} turned down, {d['accepted']} accepted in 30 "
                f"days (bar {bar:g}%): it is proposing the wrong things.",
                d["acceptance_rate"], bar)
        if d["oldest_waiting_hours"] and d["oldest_waiting_hours"] > BACKLOG_HOURS:
            add("backlog", WARNING,
                f"{d['waiting']} proposal(s) waiting, the oldest "
                f"{int(d['oldest_waiting_hours'] // 24)} days",
                "Accept or turn them down on Agents.",
                d["oldest_waiting_hours"], BACKLOG_HOURS)

    base, p95 = m["baseline_p95_ms"], run.get("p95_ms")
    if base and p95 and p95 > SLOW_FLOOR_MS and p95 > SLOW_TIMES * base:
        add("slow", WARNING,
            f"runs are slow ({p95 / 1000:.1f} s against a normal "
            f"{base / 1000:.1f} s)",
            "Its slowest runs in 24 hours took over three times as long as "
            "its own normal over the last two weeks.", p95, SLOW_TIMES * base)

    res = m["result"]
    bar = float(settings.agent_eval_min_chat if key == CHAT
                else settings.agent_eval_min_result)
    if res["total"] >= MIN_RESULTS and res["rate"] is not None and res["rate"] < bar:
        add("low_result", CRITICAL if res["rate"] < bar - 30 else WARNING,
            f"{res['label'].lower()}: {res['rate']:g}% {res['basis']}",
            f"{res['good']} of {res['total']} (bar {bar:g}%). {res['note']}.",
            res["rate"], bar)
    return found


def update_issues(session, measured: List[dict], settings,
                  now: datetime) -> dict:
    """Open what is newly wrong, refresh what still is, resolve the rest."""
    current = {(m["key"], c["check"]): c
               for m in measured for c in checks(m, settings)}
    open_rows = {(i.agent_key, i.check_key): i for i in session.execute(
        select(AgentEvalIssue).where(AgentEvalIssue.status == OPEN)).scalars()}
    opened = resolved = 0
    for key, c in current.items():
        row = open_rows.get(key)
        if row is None:
            session.add(AgentEvalIssue(
                agent_key=key[0], check_key=key[1], severity=c["severity"],
                status=OPEN, title=c["title"][:300], detail=c["detail"],
                value=c["value"], limit_value=c["limit"],
                first_seen_at=now, last_seen_at=now))
            opened += 1
            logger.warning("agent_eval: issue opened — %s", c["title"])
        else:
            row.severity, row.title = c["severity"], c["title"][:300]
            row.detail, row.value, row.limit_value = c["detail"], c["value"], c["limit"]
            row.last_seen_at = now
    for key, row in open_rows.items():
        if key not in current:
            row.status, row.resolved_at = RESOLVED, now
            resolved += 1
            logger.info("agent_eval: issue resolved — %s", row.title)
    return {"opened": opened, "resolved": resolved, "open": len(current)}


# ---- 3. history ----------------------------------------------------------------

SNAPSHOT_KEYS = ("success_rate", "on_schedule", "p50_ms", "p95_ms", "runs",
                 "failed", "findings", "quieted")


def save_snapshots(session, measured: List[dict], now: datetime) -> int:
    """Today's row per agent (the day's last check wins)."""
    today = _today(now)
    existing = {s.agent_key: s for s in session.execute(
        select(AgentEvalSnapshot).where(AgentEvalSnapshot.day == today)).scalars()}
    for m in measured:
        metrics = {k: m["run"].get(k) for k in SNAPSHOT_KEYS}
        metrics.update({
            "result_rate": m["result"]["rate"], "result_good": m["result"]["good"],
            "result_total": m["result"]["total"],
            "acceptance_rate": m["decisions"]["acceptance_rate"],
            "enabled": m["enabled"],
        })
        row = existing.get(m["key"])
        if row is None:
            session.add(AgentEvalSnapshot(agent_key=m["key"], day=today,
                                          score=m["score"], metrics=metrics,
                                          updated_at=now))
        else:
            row.score, row.metrics, row.updated_at = m["score"], metrics, now
    return len(measured)


def history(session, days: int = 30, agent: Optional[str] = None,
            now: Optional[datetime] = None) -> List[dict]:
    now = now or datetime.now(timezone.utc)
    since = _today(now) - timedelta(days=max(1, days) - 1)
    q = select(AgentEvalSnapshot).where(AgentEvalSnapshot.day >= since)
    if agent:
        q = q.where(AgentEvalSnapshot.agent_key == agent)
    rows = session.execute(q.order_by(AgentEvalSnapshot.day)).scalars().all()
    return [{"agent": r.agent_key, "day": r.day.isoformat(), "score": r.score,
             **(r.metrics or {})} for r in rows]


# ---- 4. improving itself -------------------------------------------------------

def muted_kinds(session, key: str) -> set:
    """Kinds of proposal this agent no longer asks about (mute_rejected in
    force). Read by agent_runner on every run."""
    rows = session.execute(select(AgentImprovement.change).where(
        AgentImprovement.agent_key == key,
        AgentImprovement.kind == "mute_rejected",
        AgentImprovement.status == APPLIED)).scalars().all()
    return {(c or {}).get("finding_kind") for c in rows if c}


def _known(session, kind: str) -> List[AgentImprovement]:
    return list(session.execute(select(AgentImprovement).where(
        AgentImprovement.kind == kind)).scalars())


def _phrasings_of(entry) -> List[str]:
    from app.services import knowledge_service
    return [knowledge_service.normalized(p)
            for p in [entry.question] + (entry.phrasings or "").splitlines()
            if p.strip()]


def _do_phrasing(session, imp: AgentImprovement) -> Optional[str]:
    """Add the wording to its entry. None when done, else why not."""
    import uuid as _uuid

    from app.models.knowledge import KnowledgeEntry, KnowledgeMiss
    change = imp.change or {}
    entry = session.get(KnowledgeEntry, _uuid.UUID(change["entry_id"]))
    if entry is None or not entry.active:
        return "that Knowledge Base entry is gone or switched off"
    wording = change["phrasing"].strip()
    if change.get("normalized") not in _phrasings_of(entry):
        entry.phrasings = ((entry.phrasings or "").rstrip("\n") + "\n" + wording).strip("\n")
        entry.updated_by = "Agent health (learned)"
    miss = session.execute(select(KnowledgeMiss).where(
        KnowledgeMiss.normalized == change.get("normalized"))).scalars().first()
    if miss is not None:
        session.delete(miss)
    return None


def _undo_phrasing(session, imp: AgentImprovement) -> Optional[str]:
    import uuid as _uuid

    from app.models.knowledge import KnowledgeEntry
    from app.services import knowledge_service
    change = imp.change or {}
    entry = session.get(KnowledgeEntry, _uuid.UUID(change["entry_id"]))
    if entry is None:
        return None          # the entry is gone, so the wording is too
    keep = [line for line in (entry.phrasings or "").splitlines()
            if knowledge_service.normalized(line) != change.get("normalized")]
    entry.phrasings = "\n".join(keep)
    return None


def _set_agent(session, key: str, enabled: bool) -> Optional[str]:
    from app.services import agent_runner
    if not agent_registry.exists(key):
        return f"there is no {key} agent"
    agent_runner.state_for(session, key).enabled = enabled
    return None


def _new(session, auto: bool, **fields) -> AgentImprovement:
    imp = AgentImprovement(status=APPLIED if auto else PROPOSED,
                           automatic=auto, **fields)
    if auto:
        imp.decided_by = "the agents (by themselves)"
        imp.decided_at = datetime.now(timezone.utc)
    session.add(imp)
    return imp


def learn(session, settings, now: datetime) -> dict:
    """Close proposals no longer needed, then look for new lessons."""
    from app.models.knowledge import KnowledgeEntry, KnowledgeMiss
    from app.services import knowledge_service

    auto = bool(settings.agent_eval_auto_improve)
    applied = proposed = closed = 0
    states = _states(session)

    # -- proposals that are no longer needed ---------------------------------
    misses = {m.normalized: m for m in session.execute(
        select(KnowledgeMiss)).scalars()}
    for imp in session.execute(select(AgentImprovement).where(
            AgentImprovement.status == PROPOSED)).scalars():
        change = imp.change or {}
        gone = None
        if imp.kind == "kb_entry" and change.get("normalized") not in misses:
            gone = "The Knowledge Base answers it now."
        elif imp.kind == "disable_failing":
            st = states.get(imp.agent_key)
            if st is not None and not (st.consecutive_failures or 0):
                gone = "The agent works again."
        if gone:
            imp.status, imp.note, imp.decided_at = CLOSED, gone, now
            imp.decided_by = "the agents (by themselves)"
            closed += 1

    # -- mute_rejected: stop asking what people always turn down --------------
    seen = {(i.agent_key, (i.change or {}).get("finding_kind"))
            for i in _known(session, "mute_rejected")}
    tally: Dict[Tuple[str, str], List[int]] = {}
    for f in session.execute(select(AgentFinding).where(
            AgentFinding.proposal.isnot(None),
            AgentFinding.status.in_((ACCEPTED, REJECTED)),
            AgentFinding.decided_at >= now - timedelta(days=60))).scalars():
        t = tally.setdefault((f.agent_key, finding_kind(f.title)), [0, 0])
        t[0 if f.status == ACCEPTED else 1] += 1
    for (key, kind), (acc, rej) in sorted(tally.items()):
        if acc == 0 and rej >= MUTE_AFTER_REJECTIONS and (key, kind) not in seen:
            _new(session, auto, agent_key=key, kind="mute_rejected",
                 title=f"{name_of(key)}: stop asking “{kind}”",
                 evidence=(f"Turned down {rej} times in 60 days and never "
                           "accepted. It will still be reported, just not "
                           "asked about."),
                 change={"finding_kind": kind})
            applied += auto
            proposed += not auto

    # -- kb_phrasing: learn a new wording from a quick rephrase ---------------
    done = {((i.change or {}).get("entry_id"), (i.change or {}).get("normalized"))
            for i in _known(session, "kb_phrasing")}
    turns = session.execute(select(AssistantTurn).where(
        AssistantTurn.created_at >= now - timedelta(days=3))
        .order_by(AssistantTurn.asked_by, AssistantTurn.created_at)).scalars().all()
    for first, then in zip(turns, turns[1:]):
        if (first.asked_by != then.asked_by or first.answered
                or not first.normalized or then.kind != "knowledge"
                or then.entry_id is None
                or _aware(then.created_at) - _aware(first.created_at)
                > timedelta(minutes=REPHRASE_MINUTES)):
            continue
        if not set(first.normalized.split()) & set(then.normalized.split()):
            continue          # a new topic, not the same question again
        pair = (str(then.entry_id), first.normalized)
        if pair in done:
            continue
        entry = session.get(KnowledgeEntry, then.entry_id)
        if entry is None or not entry.active or first.normalized in _phrasings_of(entry):
            continue
        done.add(pair)
        imp = _new(session, auto, agent_key=CHAT, kind="kb_phrasing",
                   title=f"Chat: answer “{first.question[:120]}” with "
                         f"“{entry.question[:120]}”",
                   evidence=(f"{first.asked_by or 'Someone'} asked it, got no "
                             "answer, and within a few minutes asked again in "
                             "other words and got this entry."),
                   change={"entry_id": str(entry.id), "phrasing": first.question,
                           "normalized": first.normalized})
        if auto:
            why = _do_phrasing(session, imp)
            if why:
                imp.status, imp.note = CLOSED, why
            else:
                applied += 1
        else:
            proposed += 1

    # -- kb_entry: a question nobody answers, asked again and again ------------
    asked_for = {(i.change or {}).get("normalized")
                 for i in _known(session, "kb_entry")
                 if i.status in (PROPOSED, DISMISSED)}
    for miss in misses.values():
        if miss.times_asked >= KB_ENTRY_AFTER and miss.normalized not in asked_for \
                and session.execute(select(KnowledgeMiss.id).where(
                    KnowledgeMiss.id == miss.id)).first() is not None:
            _new(session, False, agent_key=CHAT, kind="kb_entry",
                 title=f"Write an answer for “{miss.question[:200]}”",
                 evidence=(f"Asked {miss.times_asked} times and the chat could "
                           "not answer. Knowledge Base → Unanswered questions."),
                 change={"normalized": miss.normalized,
                         "question": miss.question, "miss_id": str(miss.id)})
            proposed += 1

    # -- disable_failing: an agent that keeps failing --------------------------
    bar = max(4, 2 * int(settings.alert_agent_failures))
    waiting = {i.agent_key for i in _known(session, "disable_failing")
               if i.status == PROPOSED}
    for key, st in states.items():
        if st.enabled and (st.consecutive_failures or 0) >= bar \
                and key not in waiting and agent_registry.exists(key):
            _new(session, False, agent_key=key, kind="disable_failing",
                 title=f"Switch the {name_of(key)} off until it is fixed",
                 evidence=(f"{st.consecutive_failures} runs in a row failed. "
                           f"Last: {(st.last_summary or '')[:200]}"),
                 change={"agent": key})
            proposed += 1

    return {"applied": applied, "proposed": proposed, "closed": closed}


# ---- deciding on an improvement ----------------------------------------------

class ImprovementError(Exception):
    """Plain words for the person; the router answers 409."""


def apply(session, imp: AgentImprovement, by: str) -> AgentImprovement:
    if imp.status != PROPOSED:
        raise ImprovementError(f"It is {imp.status}, so there is nothing to apply.")
    why = None
    if imp.kind == "kb_entry":
        raise ImprovementError("Write the answer in Knowledge Base → Unanswered "
                               "questions; this closes by itself once the "
                               "chat answers it.")
    if imp.kind == "kb_phrasing":
        why = _do_phrasing(session, imp)
    elif imp.kind == "disable_failing":
        why = _set_agent(session, imp.agent_key, False)
    if why:
        raise ImprovementError(f"Could not apply: {why}.")
    imp.status, imp.decided_by = APPLIED, by
    imp.decided_at = datetime.now(timezone.utc)
    _audit(session, "agent_improvement_applied", imp, by)
    return imp


def dismiss(session, imp: AgentImprovement, by: str) -> AgentImprovement:
    if imp.status != PROPOSED:
        raise ImprovementError(f"It is {imp.status}, so there is nothing to "
                               "turn down.")
    imp.status, imp.decided_by = DISMISSED, by
    imp.decided_at = datetime.now(timezone.utc)
    _audit(session, "agent_improvement_dismissed", imp, by)
    return imp


def undo(session, imp: AgentImprovement, by: str) -> AgentImprovement:
    if imp.status != APPLIED:
        raise ImprovementError(f"It is {imp.status}, so there is nothing to undo.")
    why = None
    if imp.kind == "kb_phrasing":
        why = _undo_phrasing(session, imp)
    elif imp.kind == "disable_failing":
        why = _set_agent(session, imp.agent_key, True)
    elif imp.kind not in ("mute_rejected",):
        why = "this kind cannot be undone here"
    if why:
        raise ImprovementError(f"Could not undo: {why}.")
    imp.status = UNDONE
    imp.note = f"Undone by {by} on {datetime.now(timezone.utc):%d %b %Y %H:%M} UTC"
    _audit(session, "agent_improvement_undone", imp, by)
    return imp


def _audit(session, action: str, imp: AgentImprovement, by: str) -> None:
    from app.models.audit_log import AuditLog
    session.add(AuditLog(action=action, resource_type="agent_improvement",
                         resource_id=str(imp.id), result="success",
                         metadata_json={"by": by, "kind": imp.kind,
                                        "agent": imp.agent_key,
                                        "title": imp.title[:300]}))


# ---- the whole check -------------------------------------------------------------

def evaluate(session, now: Optional[datetime] = None) -> dict:
    """Measure, keep today's history, update issues, learn. Commits."""
    from sqlalchemy import text

    from app.config import get_settings
    from app.workspace_context import current_workspace_id
    now = now or datetime.now(timezone.utc)
    settings = get_settings()
    # One check at a time per workspace (the timer and "Check now" could
    # meet): held until the commit below.
    session.execute(text("SELECT pg_advisory_xact_lock(7262252, hashtext(:ws))"),
                    {"ws": str(current_workspace_id())})
    measured = measure(session, now)
    save_snapshots(session, measured, now)
    issues = update_issues(session, measured, settings, now)
    lessons = learn(session, settings, now)
    session.commit()
    logger.info("agent_eval: %d agent(s) checked; issues %s; improvements %s",
                len(measured), issues, lessons)
    return {"agents": len(measured), "issues": issues, "improvements": lessons}


def _improvement_row(i: AgentImprovement) -> dict:
    return {"id": str(i.id), "agent": i.agent_key, "agent_name": name_of(i.agent_key),
            "kind": i.kind, "title": i.title, "evidence": i.evidence,
            "change": i.change, "status": i.status, "automatic": i.automatic,
            "created_at": _iso(_aware(i.created_at)), "decided_by": i.decided_by,
            "decided_at": _iso(_aware(i.decided_at)), "note": i.note,
            "can_undo": i.status == APPLIED and i.kind in (
                "mute_rejected", "kb_phrasing", "disable_failing")}


def issue_row(i: AgentEvalIssue) -> dict:
    return {"id": str(i.id), "agent": i.agent_key, "agent_name": name_of(i.agent_key),
            "check": i.check_key, "severity": i.severity, "status": i.status,
            "title": i.title, "detail": i.detail, "value": i.value,
            "limit": i.limit_value,
            "first_seen_at": _iso(_aware(i.first_seen_at)),
            "last_seen_at": _iso(_aware(i.last_seen_at)),
            "resolved_at": _iso(_aware(i.resolved_at))}


def issues(session, status: str = OPEN, limit: int = 200) -> List[dict]:
    q = select(AgentEvalIssue)
    if status in (OPEN, RESOLVED):
        q = q.where(AgentEvalIssue.status == status)
    rows = session.execute(q.order_by(AgentEvalIssue.last_seen_at.desc())
                           .limit(limit)).scalars().all()
    order = {CRITICAL: 0, WARNING: 1}
    return [issue_row(i) for i in sorted(
        rows, key=lambda i: (i.status != OPEN, order.get(i.severity, 2)))]


def improvements(session, limit: int = 50) -> dict:
    rows = session.execute(select(AgentImprovement).order_by(
        AgentImprovement.created_at.desc()).limit(500)).scalars().all()
    waiting = [_improvement_row(i) for i in rows if i.status == PROPOSED]
    done = [_improvement_row(i) for i in rows if i.status != PROPOSED][:limit]
    return {"waiting": waiting, "history": done,
            "in_force": sum(1 for i in rows if i.status == APPLIED)}


def status_of(m: dict, open_issues: Iterable[dict]) -> str:
    if not m["enabled"]:
        return "off"
    severities = {i["severity"] for i in open_issues if i["agent"] == m["key"]}
    if CRITICAL in severities or (m["score"] is not None and m["score"] < 60):
        return "red"
    if WARNING in severities or (m["score"] is not None and m["score"] < 85):
        return "amber"
    return "green" if m["score"] is not None else "grey"


def overview(session, now: Optional[datetime] = None) -> dict:
    """Everything the Agent health screen shows (no writes)."""
    from app.config import get_settings
    from app.models.knowledge import KnowledgeMiss
    now = now or datetime.now(timezone.utc)
    s = get_settings()
    measured = measure(session, now)
    open_issues = issues(session, OPEN)
    trend = {}
    for row in history(session, 14, now=now):
        trend.setdefault(row["agent"], []).append(
            {"day": row["day"], "score": row["score"]})
    for m in measured:
        m["status"] = status_of(m, open_issues)
        m["open_issues"] = sum(1 for i in open_issues if i["agent"] == m["key"])
        m["trend"] = trend.get(m["key"], [])
    checked = session.execute(select(func.max(AgentEvalSnapshot.updated_at))).scalar()
    unanswered = session.execute(select(KnowledgeMiss).order_by(
        KnowledgeMiss.times_asked.desc(), KnowledgeMiss.last_asked_at.desc())
        .limit(5)).scalars().all()
    scored = [m["score"] for m in measured if m["score"] is not None]
    return {
        "now": now.isoformat(),
        "checked_at": _iso(_aware(checked)),
        "overall": int(round(sum(scored) / len(scored))) if scored else None,
        "agents": measured,
        "issues": open_issues,
        "improvements": improvements(session),
        "unanswered": [{"question": u.question, "times_asked": u.times_asked}
                       for u in unanswered],
        "bars": {"success": s.agent_eval_min_success,
                 "result": s.agent_eval_min_result,
                 "chat": s.agent_eval_min_chat,
                 "acceptance": s.agent_eval_min_acceptance,
                 "agent_failures": s.alert_agent_failures},
        "auto_improve": bool(s.agent_eval_auto_improve),
    }


# ---- the daily summary email --------------------------------------------------------

SUMMARY_ACTION = "agent_health_summary"


def summary_due(session, now: datetime) -> Optional[str]:
    """None when the daily email should go now, else why not."""
    from app.config import get_settings
    from app.models.audit_log import AuditLog
    from app.workers.verify_old_csps_worker import send_zone
    s = get_settings()
    if not s.agent_eval_summary_on:
        return "off (Settings → Agent health → Daily agent health email)"
    local = now.astimezone(send_zone())
    if local.hour < int(s.agent_eval_summary_hour):
        return "not the hour yet"
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    last = session.execute(select(func.max(AuditLog.created_at)).where(
        AuditLog.action == SUMMARY_ACTION, AuditLog.result == "success")).scalar()
    if last and _aware(last) >= midnight:
        return "already sent today"
    return None


def summary_text(data: dict, brand: str, link: str) -> str:
    lines = [f"{brand} — agent health, {data['now'][:10]}", ""]
    overall = data["overall"]
    lines.append(f"Overall score: {overall if overall is not None else '—'} / 100")
    lines.append("")
    for m in data["agents"]:
        score = "off" if not m["enabled"] else (
            m["score"] if m["score"] is not None else "no data yet")
        res = m["result"]
        rate = f"{res['rate']:g}%" if res["rate"] is not None else "—"
        lines.append(f"• {m['name']}: {score} ({m['status']}) — "
                     f"{res['label']}: {rate}")
    lines.append("")
    if data["issues"]:
        lines.append(f"OPEN ISSUES ({len(data['issues'])})")
        for i in data["issues"]:
            lines.append(f"• [{i['severity']}] {i['title']} — {i['detail']}")
    else:
        lines.append("No open issues.")
    lines.append("")
    since = (datetime.fromisoformat(data["now"]) - DAY).isoformat()
    learned = [i for i in data["improvements"]["history"]
               if i["automatic"] and i["status"] == APPLIED
               and (i["created_at"] or "") >= since]
    if learned:
        lines.append("LEARNED IN THE LAST 24 HOURS (each can be undone)")
        lines += [f"• {i['title']}" for i in learned]
        lines.append("")
    waiting = data["improvements"]["waiting"]
    if waiting:
        lines.append(f"WAITING FOR YOU ({len(waiting)})")
        lines += [f"• {i['title']}" for i in waiting]
        lines.append("")
    lines.append(f"Open Agent health: {link}")
    lines.append("— " + brand)
    return "\n".join(lines)


def run_summary(session, now: Optional[datetime] = None, send=None) -> dict:
    """The daily email: once a day at the workspace's hour, server only,
    to the alert recipients minus anyone who switched it off."""
    from app.config import get_settings
    from app.models.audit_log import AuditLog
    from app.services import alerts, message_sender, notification_prefs
    from app.workspace_context import current_workspace_id
    now = now or datetime.now(timezone.utc)
    s = get_settings()
    if s.test_copy or not message_sender.link_is_reachable(s.public_app_url):
        return {"skipped": "not the server (a laptop or the test copy sends no "
                           "daily agent health email)"}
    why = summary_due(session, now)
    if why:
        return {"skipped": why}
    to = notification_prefs.keep_wanted(session, "agent_daily",
                                        alerts.recipients(session))
    if not to:
        return {"skipped": "no one to send it to"}
    data = overview(session, now)
    link = s.public_app_url.rstrip("/") + "/admin?section=agent-health"
    text = summary_text(data, s.brand_name, link)
    n = len(data["issues"])
    subject = (f"{s.brand_name}: agent health {data['overall'] if data['overall'] is not None else '—'}"
               f"/100, {n} open issue{'s' if n != 1 else ''}")
    send = send or (lambda addr, subj, body:
                    message_sender._send_email(addr, subj, body, kind="other"))
    sent, failed = [], {}
    for addr in to:
        ok, reason = send(addr, subject, text)
        if ok:
            sent.append(addr)
        else:
            failed[addr] = reason
            logger.error("agent_eval: daily summary not sent to %s: %s",
                         addr, reason)
    session.add(AuditLog(workspace_id=current_workspace_id(),
                         action=SUMMARY_ACTION, resource_type="workspace",
                         resource_id=str(current_workspace_id()),
                         result="success" if sent else "failure",
                         metadata_json={"to": sent, "failed": failed,
                                        "issues": n}))
    session.commit()
    return {"sent_to": sent, "failed": failed}
