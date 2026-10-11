# -*- coding: utf-8 -*-
"""The agents.

The property that matters most is the one these pin hardest: an agent
never changes configuration on its own. It records a proposal and waits.
An agent that could quietly remap a placeholder could quietly print the
wrong name on every certificate a template produces.

The second property is that agents did not replace the deterministic
checks. Document validation, placeholder checks and photo dimensions are
where they were, and no agent overrides them.
"""


import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.agent import (
    FAILED, INFORMATIONAL, OK, PROPOSED, SKIPPED, AgentRun,
)
from app.services import agent_registry as reg
from app.services import agent_runner as runner
from app.services import agents as _impl  # noqa: F401  (registers the work)
from app.services.agent_runner import Finding, Outcome
from app.workspace_context import workspace
from tests.conftest import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="module")
def _engine(migrated_db):
    engine = create_engine(
        get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"))
    yield engine
    engine.dispose()


@pytest.fixture
def db(_engine):
    with Session(_engine) as session:
        session.execute(text(
            "TRUNCATE agent_findings, agent_runs, agent_states "
            "RESTART IDENTITY CASCADE"))
        session.commit()
        with workspace(DEFAULT_WORKSPACE_ID):
            yield session


# ---- the catalogue -------------------------------------------------------

async def test_there_are_six_agents():
    assert len(reg.all_agents()) == 6
    assert set(reg.keys()) == {
        "setup", "data", "verification", "document", "communication",
        "monitoring",
    }


async def test_every_agent_has_an_implementation():
    """An agent nobody implemented would silently do nothing forever."""
    missing = set(reg.keys()) - set(runner.implemented())
    assert not missing, f"{missing} are described but do nothing"


async def test_every_agent_says_what_it_owns_and_may_do():
    for agent in reg.all_agents():
        assert agent.owns and agent.owns.endswith("?"), agent.key
        assert agent.does, agent.key
        assert agent.may, agent.key
        assert agent.proposes, agent.key


async def test_the_communication_agent_is_off_until_switched_on():
    """It messages real people. It must not start the day it deploys."""
    assert reg.get("communication").enabled_by_default is False


async def test_the_document_agent_proposes_nothing():
    """Validation stays deterministic; no agent may override it."""
    proposes = " ".join(reg.get("document").proposes).lower()
    assert "nothing" in proposes
    assert "deterministic" in proposes


# ---- an agent never changes configuration by itself ----------------------

async def test_a_finding_with_a_proposal_waits_for_a_decision():
    finding = Finding(title="Map this placeholder",
                      proposal={"action": "map_placeholders"})
    assert finding.status == PROPOSED


async def test_a_finding_without_a_proposal_is_just_information():
    assert Finding(title="3 records incomplete").status == INFORMATIONAL


async def test_a_proposal_is_recorded_not_applied(db, monkeypatch):
    """The whole safety model in one test."""
    applied = []

    def pretend(session):
        return Outcome(
            summary="would change something",
            findings=[Finding(
                title="Remap CSP Name",
                proposal={"action": "map_placeholders", "field": "csp_name"},
            )],
        )

    monkeypatch.setitem(runner._WORK, "setup", pretend)
    record = runner.run(db, "setup", force=True)

    assert record.status == OK
    assert len(record.findings) == 1
    assert record.findings[0].status == PROPOSED
    assert applied == [], "the agent applied its own proposal"


# ---- running, and being accountable for it -------------------------------

async def test_every_run_is_written_down(db):
    runner.run(db, "monitoring", triggered_by="a test", force=True)
    runs = db.execute(
        select(AgentRun).where(AgentRun.agent_key == "monitoring")
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].triggered_by == "a test"
    assert runs[0].duration_ms is not None


async def test_a_disabled_agent_says_it_was_skipped(db):
    """'Found nothing' and 'never looked' must not look the same."""
    state = runner.state_for(db, "data")
    state.enabled = False
    db.commit()

    record = runner.run(db, "data")
    assert record.status == SKIPPED
    assert "switched off" in record.summary


async def test_forcing_runs_a_disabled_agent(db):
    runner.state_for(db, "data").enabled = False
    db.commit()
    assert runner.run(db, "data", force=True).status == OK


async def test_a_failing_agent_records_its_own_failure(db, monkeypatch):
    """Including when it failed mid-statement and poisoned the session."""
    def explode(session):
        raise RuntimeError("something went wrong")

    monkeypatch.setitem(runner._WORK, "setup", explode)
    record = runner.run(db, "setup", force=True)

    assert record.status == FAILED
    assert "something went wrong" in record.error
    assert runner.state_for(db, "setup").consecutive_failures == 1


async def test_repeated_failures_are_counted(db, monkeypatch):
    monkeypatch.setitem(runner._WORK, "setup",
                        lambda s: (_ for _ in ()).throw(RuntimeError("no")))
    for _ in range(3):
        runner.run(db, "setup", force=True)
    assert runner.state_for(db, "setup").consecutive_failures == 3


async def test_a_success_clears_the_failure_count(db, monkeypatch):
    monkeypatch.setitem(runner._WORK, "setup",
                        lambda s: (_ for _ in ()).throw(RuntimeError("no")))
    runner.run(db, "setup", force=True)
    monkeypatch.setitem(runner._WORK, "setup",
                        lambda s: Outcome(summary="fine"))
    runner.run(db, "setup", force=True)
    assert runner.state_for(db, "setup").consecutive_failures == 0


async def test_one_failing_agent_does_not_stop_the_others(db, monkeypatch):
    monkeypatch.setitem(runner._WORK, "data",
                        lambda s: (_ for _ in ()).throw(RuntimeError("no")))
    runs = runner.run_all(db, triggered_by="a test")
    statuses = {r.agent_key: r.status for r in runs}
    assert statuses["data"] == FAILED
    assert statuses["monitoring"] in (OK, SKIPPED)


async def test_on_demand_agents_are_not_run_on_a_schedule(db):
    """The Setup Agent reads configuration; it has no reason to poll."""
    keys = {r.agent_key for r in runner.run_all(db)}
    assert "setup" not in keys


# ---- the agents actually work against real data --------------------------

@pytest.mark.parametrize("key", ["setup", "data", "verification",
                                 "document", "monitoring"])
async def test_each_agent_runs_and_says_something(db, key):
    record = runner.run(db, key, force=True)
    assert record.status == OK, record.error
    assert record.summary, f"{key} ran but said nothing"


async def test_an_unknown_agent_is_refused(db):
    with pytest.raises(KeyError):
        runner.run(db, "not-an-agent")


async def test_an_implementation_must_match_a_registered_agent():
    """Otherwise something runs that nobody can describe."""
    with pytest.raises(KeyError):
        runner.performs("ghost")(lambda s: Outcome(summary=""))
