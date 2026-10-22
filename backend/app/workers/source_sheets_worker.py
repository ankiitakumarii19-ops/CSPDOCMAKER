"""
CSP DocMaker — read the Calling and Lead raw data sheets (tracker No. 121)

Every SOURCE_SHEETS_INTERVAL_MINUTES, in the Eko workspace only (the sheet
ids are Eko's). What it does: services/source_sheets.py. Switched off while
CALLING_SHEET_ID / LEAD_SHEET_ID are not set.
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_configured_workspace

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.sync_source_sheets", bind=True,
                 max_retries=2, default_retry_delay=120)
@for_configured_workspace
def sync_source_sheets(self):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.services import source_sheets

    settings = get_settings()
    if not (settings.calling_sheet_id and settings.lead_sheet_id):
        return {"skipped": "CALLING_SHEET_ID / LEAD_SHEET_ID not set"}
    engine = create_engine(settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            try:
                summary = source_sheets.run(session)
            except Exception as e:
                session.rollback()
                logger.error("source_sheets_worker: the pass failed, nothing "
                             "changed: %s: %s", type(e).__name__, e,
                             exc_info=True)
                raise self.retry(exc=e)
            return {"summary": summary.text(),
                    "went_live": summary.went_live,
                    "imported_new": summary.imported_new,
                    "skipped": summary.skipped}
    finally:
        engine.dispose()
