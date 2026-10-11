"""
CSP DocMaker — running an agent and recording what it did

Every agent runs through here, so every run is written down the same way:
what it looked at, what it found, how long it took, and whether anybody
asked for it.

A finding is how an agent speaks. Two kinds:

    informational   something worth knowing
    proposed        something it would change, if allowed

Nothing with a proposal is ever applied by the agent itself. A Super Admin
accepts or rejects it. An agent that could quietly remap a field could
quietly print the wrong name on every certificate, and the gap between
those two sentences is the entire reason for this design.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import (
    FAILED, INFO, INFORMATIONAL, OK, PROPOSED, SKIPPED, AgentFinding, AgentRun,
    AgentState,
)
from app.services import agent_registry

logger = logging.getLogger(__name__)


@dataclass
class Finding:
    """Something an agent noticed. Plain data until it is written down."""

    title: str
    detail: str = ""
    severity: str = INFO
    proposal: Optional[dict] = None
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None

    @property
    def status(self) -> str:
        # A finding carrying a proposal is waiting on a decision; one
        # without is simply reporting.
        return PROPOSED if self.proposal else INFORMATIONAL


@dataclass
class Outcome:
    """What an agent has to say when it finishes."""

    summary: str
    detail: dict = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)


# agent key -> the function that does the work
_WORK: Dict[str, Callable[[Session], Outcome]] = {}


def performs(key: str):
    """Attach an implementation to a registered agent."""
    def attach(fn):
        if not agent_registry.exists(key):
            raise KeyError(
                f"{key!r} has an implementation but is not in the registry. "
                f"An agent nobody can describe should not be running."
            )
        _WORK[key] = fn
        return fn
    return attach


def is_implemented(key: str) -> bool:
    return key in _WORK


def implemented() -> List[str]:
    return sorted(_WORK)


def state_for(session: Session, key: str) -> AgentState:
    """This workspace's switch for an agent, created on first sight."""
    state = session.execute(
        select(AgentState).where(AgentState.agent_key == key)
    ).scalars().first()
    if state is None:
        state = AgentState(
            agent_key=key,
            enabled=agent_registry.get(key).enabled_by_default,
        )
        session.add(state)
        session.flush()
    return state


def _load_implementations() -> None:
    """Make sure the agents' implementations are attached before running one.

    The `@performs` decorators live in app.services.agents, so an agent has
    an implementation only once that module has been imported. It used to
    be imported by the agent router alone — which meant it happened in the
    API process and NOT in the Celery worker, where the scheduled runs
    actually happen.

    The symptom of that would have been the worst kind: every scheduled run
    recording "has no implementation yet" and doing nothing, while the
    screen showed the agents as running. Importing it here means anyone who
    runs an agent gets the implementations, whatever process they are in.

    Imported inside the function rather than at the top because
    app.services.agents imports `performs` from this module.
    """
    from app.services import agents  # noqa: F401  (registers the performers)


def run(session: Session, key: str, triggered_by: Optional[str] = None,
        force: bool = False) -> AgentRun:
    """Run one agent and write down what happened.

    A disabled agent is skipped rather than silently doing nothing — the
    run record says so, which is the difference between "it found nothing"
    and "it never looked".
    """
    _load_implementations()

    agent = agent_registry.get(key)
    state = state_for(session, key)

    if not state.enabled and not force:
        record = AgentRun(
            agent_key=key, status=SKIPPED, triggered_by=triggered_by,
            summary=f"{agent.name} is switched off for this workspace.",
        )
        session.add(record)
        session.commit()
        return record

    work = _WORK.get(key)
    if work is None:
        record = AgentRun(
            agent_key=key, status=SKIPPED, triggered_by=triggered_by,
            summary=f"{agent.name} has no implementation yet.",
        )
        session.add(record)
        session.commit()
        return record

    began = time.monotonic()
    record = AgentRun(agent_key=key, status=OK, triggered_by=triggered_by,
                      summary="")
    session.add(record)
    session.flush()

    from app import telemetry

    try:
        with telemetry.operation(f"agent {key}", "agent_runner",
                                 agent=key, triggered_by=triggered_by or "schedule"):
            outcome = work(session)
            # What the agent decided — operational facts, no internals.
            logger.info("[AGENT] %s: %s (%d finding(s)%s)", key,
                        outcome.summary, len(outcome.findings),
                        "; " + "; ".join(f.title for f in outcome.findings[:5])
                        if outcome.findings else "")
        record.status = OK
        record.summary = outcome.summary
        record.detail = outcome.detail
        for finding in outcome.findings:
            record.findings.append(AgentFinding(
                agent_key=key,
                severity=finding.severity,
                status=finding.status,
                title=finding.title,
                detail=finding.detail,
                proposal=finding.proposal,
                subject_type=finding.subject_type,
                subject_id=finding.subject_id,
            ))
        state.consecutive_failures = 0
    except Exception as e:
        # The agent may have failed mid-statement, which leaves the
        # transaction unusable — including for writing down that it
        # failed. Roll back first, then re-attach the run record.
        try:
            session.rollback()
        except Exception as rollback_error:
            # Recorded, not hidden: the original error below is what failed
            # the agent; this only says the clean-up also had trouble.
            logger.warning("agent_runner: rollback after %s failure also "
                           "failed: %s: %s", key,
                           type(rollback_error).__name__, rollback_error,
                           exc_info=True)
        record = session.merge(record)
        record.status = FAILED
        # Keep the traceback with the run, so the run history shows where.
        import traceback as _tb
        record.error = (f"{type(e).__name__}: {e}" + chr(10)
                        + "".join(_tb.format_exception(type(e), e,
                                                       e.__traceback__))[-4000:])
        record.summary = f"{agent.name} failed: {type(e).__name__}"
        state = state_for(session, key)
        state.consecutive_failures = (state.consecutive_failures or 0) + 1
        logger.error("agent_runner: %s failed (traceback logged by its "
                     "operation and kept on the run record): %s: %s",
                     key, type(e).__name__, e)

    record.duration_ms = int((time.monotonic() - began) * 1000)
    state.last_run_at = datetime.now(timezone.utc)
    state.last_status = record.status
    state.last_summary = record.summary
    session.commit()

    logger.info("agent_runner: %s %s in %dms — %s",
                key, record.status, record.duration_ms, record.summary)
    return record


def run_all(session: Session, triggered_by: Optional[str] = None) -> List[AgentRun]:
    """Run every scheduled agent. One failing does not stop the others."""
    runs = []
    for agent in agent_registry.all_agents():
        if agent.trigger == agent_registry.ON_DEMAND:
            continue
        runs.append(run(session, agent.key, triggered_by=triggered_by))
    return runs
