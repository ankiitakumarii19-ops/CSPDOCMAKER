"""
CSP DocMaker — Agent health on a timer (No. 252)

Every 15 minutes, for each workspace: measure every agent, keep today's
history row, open / resolve issues, learn (services/agent_eval.evaluate),
then send the daily agent health email if it is due (run_summary). Issue
emails go out through the alert job (services/alerts.py), like every other
alert.
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_each_workspace

logger = logging.getLogger(__name__)

EVERY_SECONDS = 15 * 60


@celery_app.task(name="workers.agent_evaluation", bind=True, max_retries=0)
@for_each_workspace
def agent_evaluation(self):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.services import agent_eval

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            result = agent_eval.evaluate(session)
            try:
                result["summary"] = agent_eval.run_summary(session)
            except Exception as e:
                # The check is done and kept; only the email failed.
                session.rollback()
                logger.error("agent_evaluation: the daily summary failed: "
                             "%s: %s", type(e).__name__, e, exc_info=True)
                result["summary"] = {"failed": f"{type(e).__name__}: {e}"}
    finally:
        engine.dispose()
    logger.info("agent_evaluation: %s", result)
    return result
