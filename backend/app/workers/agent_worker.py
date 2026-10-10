"""
CSP DocMaker — running the agents on a schedule

The agents were built, registered, enabled and shown on screen as
"Running — every 15 min", and nothing ever invoked them. They had run
three times, each of those a person clicking "Run now". The screen was
reading `enabled` from the database and the interval from the registry,
and neither of those means anything is calling them.

This is the piece that was missing.

One task, taking the agent's key, scheduled once per agent at the interval
that agent declares. The schedule is built from the registry rather than
typed out again (see celery_app), so an agent added later is scheduled by
being registered, and an agent whose interval changes does not need this
file touched.

Each run happens once inside each active workspace, like every other
scheduled task — an agent reads scoped tables, and without a workspace in
force it would see nothing at all.
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_each_workspace

logger = logging.getLogger(__name__)


@celery_app.task(
    name="workers.run_agent",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
@for_each_workspace
def run_agent(self, key: str):
    """Run one agent in this workspace and record what it found.

    A disabled agent is not skipped here but inside the runner, which
    writes a run saying it was disabled. That distinction matters when
    somebody asks why nothing happened: "it found nothing" and "it never
    looked" are different answers.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.services import agent_runner

    engine = create_engine(
        get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"),
        pool_pre_ping=True,
    )
    try:
        with Session(engine) as session:
            record = agent_runner.run(session, key, triggered_by="schedule")
            summary = getattr(record, "summary", "") or ""
            logger.info("agent_worker: %s — %s", key, summary or "nothing to do")
            return {
                "agent": key,
                "status": getattr(record, "status", ""),
                "summary": summary,
            }
    finally:
        engine.dispose()
