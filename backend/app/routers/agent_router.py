"""
CSP DocMaker — the agents, from outside

The Super Admin's alone (changed 14 Oct 2026, No. 104): reading what the
agents found, running one now, switching one on or off, and deciding what
one proposes. Admins used to share this; they no longer see the agents.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session
from app.dependencies import require_role
from app.models.agent import (
    ACCEPTED, PROPOSED, REJECTED, AgentFinding, AgentRun, AgentState,
)
from app.services import agent_registry, agent_runner
from app.services import agents as _implementations  # noqa: F401  (registers)
from app.workspace_context import current_workspace_id, workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/agents", tags=["admin", "agents"])


def _who(user: dict) -> str:
    """Who is doing this, for the log and the audit trail.

    A token always carries `sub`; it does not always carry `email`, and
    logging "None" for who deleted something is worse than useless.
    """
    return (user or {}).get("email") or (user or {}).get("sub") or "unknown"



class AgentToggle(BaseModel):
    enabled: bool


class Decision(BaseModel):
    note: Optional[str] = None


def _sync_session():
    """Agents are written against a synchronous session, like the workers."""
    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"),
        pool_pre_ping=True,
    )
    return engine, Session(engine)


@router.get("")
async def list_agents(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """Every agent, what it is for, and how its last run went."""
    states = {
        s.agent_key: s for s in
        (await session.execute(select(AgentState))).scalars().all()
    }
    out = []
    for agent in agent_registry.all_agents():
        state = states.get(agent.key)
        out.append({
            "key": agent.key,
            "name": agent.name,
            "owns": agent.owns,
            "does": agent.does,
            "may": agent.may,
            "proposes": agent.proposes,
            "trigger": agent.trigger,
            "every_minutes": agent.every_minutes,
            "implemented": agent_runner.is_implemented(agent.key),
            "enabled": state.enabled if state else agent.enabled_by_default,
            "last_run_at": state.last_run_at.isoformat()
                           if state and state.last_run_at else None,
            "last_status": state.last_status if state else None,
            "last_summary": state.last_summary if state else None,
            "consecutive_failures": state.consecutive_failures if state else 0,
        })
    return {"agents": out}


@router.get("/findings")
async def list_findings(
    only_open: bool = True,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """What the agents have noticed, newest first."""
    statement = select(AgentFinding).order_by(AgentFinding.created_at.desc())
    if only_open:
        statement = statement.where(AgentFinding.status.in_(
            (PROPOSED, "informational")))
    findings = (await session.execute(statement.limit(200))).scalars().all()

    return {
        "findings": [
            {
                "id": str(f.id),
                "agent": f.agent_key,
                "severity": f.severity,
                "status": f.status,
                "title": f.title,
                "detail": f.detail,
                "proposal": f.proposal,
                "needs_decision": f.status == PROPOSED,
                "subject_type": f.subject_type,
                "subject_id": f.subject_id,
                "created_at": f.created_at.isoformat(),
            }
            for f in findings
        ],
        "awaiting_decision": sum(1 for f in findings if f.status == PROPOSED),
    }


@router.get("/{key}/runs")
async def agent_runs(
    key: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("super_admin")),
):
    """What this agent has been doing — the Workspace Owner's alone.

    An Admin runs the agents and reads their findings; the run history is
    a different thing. It carries who triggered each pass and every error
    raised along the way, which is an audit of how the workspace has been
    operated rather than a view of the work itself.
    """
    if not agent_registry.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No agent {key!r}.")
    runs = (await session.execute(
        select(AgentRun).where(AgentRun.agent_key == key)
        .order_by(AgentRun.started_at.desc()).limit(50)
    )).scalars().all()
    return {
        "agent": key,
        "runs": [
            {
                "id": str(r.id), "status": r.status, "summary": r.summary,
                "detail": r.detail, "error": r.error,
                "duration_ms": r.duration_ms,
                "triggered_by": r.triggered_by,
                "started_at": r.started_at.isoformat(),
                "findings": len(r.findings),
            }
            for r in runs
        ],
    }


@router.post("/{key}/run")
async def run_agent(
    key: str,
    # Acting on agents is the Super Admin's (decided 12 Oct 2026, No. 88);
    # Admins can watch them.
    user=Depends(require_role("super_admin")),
):
    """Run an agent now rather than waiting for its schedule."""
    if not agent_registry.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No agent {key!r}.")

    workspace_id = current_workspace_id()
    if workspace_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No workspace could be determined for this request.")

    engine, session = _sync_session()
    try:
        with workspace(workspace_id):
            record = agent_runner.run(
                session, key, triggered_by=_who(user), force=True)
            return {
                "agent": key, "status": record.status,
                "summary": record.summary, "detail": record.detail,
                "duration_ms": record.duration_ms,
                "findings": [
                    {"severity": f.severity, "status": f.status,
                     "title": f.title, "detail": f.detail,
                     "proposal": f.proposal}
                    for f in record.findings
                ],
            }
    finally:
        session.close()
        engine.dispose()


@router.patch("/{key}")
async def toggle_agent(
    key: str,
    body: AgentToggle,
    session: AsyncSession = Depends(get_session),
    # Acting on agents is the Super Admin's (decided 12 Oct 2026, No. 88);
    # Admins can watch them.
    user=Depends(require_role("super_admin")),
):
    """Switch an agent on or off for this workspace."""
    if not agent_registry.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No agent {key!r}.")

    state = (await session.execute(
        select(AgentState).where(AgentState.agent_key == key)
    )).scalars().first()
    if state is None:
        state = AgentState(agent_key=key, enabled=body.enabled)
        session.add(state)
    else:
        state.enabled = body.enabled
        if body.enabled:
            # A fresh start: an agent turned back on should not inherit the
            # failure count that got it turned off.
            state.consecutive_failures = 0
    await session.commit()

    logger.info("agent_router: %s %s by %s", key,
                "enabled" if body.enabled else "disabled", _who(user))
    return {"agent": key, "enabled": state.enabled}


@router.post("/findings/{finding_id}/accept")
async def accept_finding(
    finding_id: str,
    body: Decision,
    session: AsyncSession = Depends(get_session),
    # Acting on agents is the Super Admin's (decided 12 Oct 2026, No. 88);
    # Admins can watch them.
    user=Depends(require_role("super_admin")),
):
    """Agree to what an agent proposed.

    Accepting records the decision. It does NOT silently apply the change:
    the proposal says what would be done, and the matching screen — a
    template's field mapping, say — is where it is actually done, by a
    person who can see the whole picture.
    """
    finding = await _finding(session, finding_id)
    if finding.status != PROPOSED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"That finding is {finding.status}, so there is nothing to "
            f"accept.")

    finding.status = ACCEPTED
    finding.decided_by = _who(user)
    from datetime import datetime, timezone
    finding.decided_at = datetime.now(timezone.utc)
    await session.commit()

    logger.info("agent_router: finding %s accepted by %s",
                finding_id, _who(user))
    return {
        "id": finding_id, "status": ACCEPTED,
        "proposal": finding.proposal,
        "note": "Recorded. Apply it on the matching screen — nothing was "
                "changed automatically.",
    }


@router.post("/findings/{finding_id}/reject")
async def reject_finding(
    finding_id: str,
    body: Decision,
    session: AsyncSession = Depends(get_session),
    # Acting on agents is the Super Admin's (decided 12 Oct 2026, No. 88);
    # Admins can watch them.
    user=Depends(require_role("super_admin")),
):
    """Decline what an agent proposed, so it stops being asked."""
    finding = await _finding(session, finding_id)
    finding.status = REJECTED
    finding.decided_by = _who(user)
    from datetime import datetime, timezone
    finding.decided_at = datetime.now(timezone.utc)
    await session.commit()
    return {"id": finding_id, "status": REJECTED}


async def _finding(session: AsyncSession, finding_id: str) -> AgentFinding:
    import uuid as _uuid

    try:
        key = _uuid.UUID(finding_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such finding.")
    finding = (await session.execute(
        select(AgentFinding).where(AgentFinding.id == key)
    )).scalars().first()
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such finding.")
    return finding
