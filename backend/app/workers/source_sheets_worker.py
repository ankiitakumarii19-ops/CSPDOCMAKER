"""
CSP DocMaker — read the Calling and Lead raw data sheets (tracker No. 121)

Every SOURCE_SHEETS_INTERVAL_MINUTES, in the Eko workspace only (the sheet
ids are Eko's). What it does: services/source_sheets.py. Switched off while
CALLING_SHEET_ID / LEAD_SHEET_ID are not set.

Each pass is a sync_runs row (source 'source_sheets'), so the screens can
show when these sheets were last read (No. 146).
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_configured_workspace

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.sync_source_sheets", bind=True,
                 max_retries=2, default_retry_delay=120)
@for_configured_workspace
def sync_source_sheets(self):
    from datetime import datetime, timezone

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.models.sync_run import SyncRun
    from app.services import source_sheets

    settings = get_settings()
    if not (settings.calling_sheet_id and settings.lead_sheet_id):
        return {"skipped": "CALLING_SHEET_ID / LEAD_SHEET_ID not set"}
    engine = create_engine(settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            run = SyncRun(source="source_sheets", status="running")
            session.add(run)
            session.commit()
            try:
                summary = source_sheets.run(session)
            except Exception as e:
                session.rollback()
                logger.error("source_sheets_worker: the pass failed, nothing "
                             "changed: %s: %s", type(e).__name__, e,
                             exc_info=True)
                run.status = "failed"
                run.error_message = f"{type(e).__name__}: {e}"[:2000]
                run.finished_at = datetime.now(timezone.utc)
                session.commit()
                raise self.retry(exc=e)
            # The pass itself is saved already; noting it must not turn it
            # into a failure (a retry would redo the work).
            try:
                run.status = "completed"
                run.rows_read = summary.calling_rows + summary.lead_rows
                run.created_count = (len(summary.imported_new)
                                     + summary.imported_old)
                run.updated_count = len(summary.became_new)
                run.skipped_count = len(summary.skipped)
                run.finished_at = datetime.now(timezone.utc)
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error("source_sheets_worker: the pass worked but its "
                             "run could not be recorded: %s: %s",
                             type(e).__name__, e, exc_info=True)
            return {"summary": summary.text(),
                    "went_live": summary.went_live,
                    "imported_new": summary.imported_new,
                    "skipped": summary.skipped}
    finally:
        engine.dispose()
