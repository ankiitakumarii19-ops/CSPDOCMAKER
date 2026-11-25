"""
CSP DocMaker — the daily contact email (No. 237)

Every 30 minutes the scheduler asks each workspace whether its daily
contact email is due (its hour has come and it has not gone today);
services/contact_report.py decides, writes and sends it.
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_each_workspace

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.contact_report", bind=True, max_retries=0)
@for_each_workspace
def contact_report(self):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.services import contact_report as cr

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            result = cr.run(session)
    finally:
        engine.dispose()
    if result.get("skipped"):
        logger.debug("contact_report: %s", result["skipped"])
    elif result.get("sent_to"):
        logger.info("contact_report: sent to %s", result["sent_to"])
    else:
        logger.error("contact_report: not sent to anyone: %s",
                     result.get("failed"))
    return result
