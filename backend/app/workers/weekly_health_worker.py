"""
CSP DocMaker — the weekly health email (No. 214, Stage 7, ZU-06)

Every hour the scheduler asks each workspace whether its weekly email is due
(its day and hour, not sent this week); services/weekly_health.py decides,
writes and sends it.
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_each_workspace

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.weekly_health", bind=True, max_retries=0)
@for_each_workspace
def weekly_health(self):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.services import weekly_health as wh

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            result = wh.run(session)
    finally:
        engine.dispose()
    if result.get("skipped"):
        logger.debug("weekly_health: %s", result["skipped"])
    else:
        logger.info("weekly_health: sent to %s", result.get("sent_to"))
    return result
