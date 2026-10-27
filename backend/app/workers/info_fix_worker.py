"""
CSP DocMaker — the app corrects INFO's AO / RBO itself (tracker No. 153)

Every INFO_AUTO_FIX_MINUTES: suggestions about AO / RBO Name (the same
correction on 2+ CSPs) are written into INFO's AO block by the app
(services/feedback_loops.auto_fix_info, services/info_writer.py). Eko's
workspace only (INFO is Eko's sheet); one run at a time; never from a copy
of the app that is not on a public address (only the server edits the
shared sheet). Off with INFO_AUTO_FIX_ENABLED=false — suggestions then wait
for a person, as before.
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_configured_workspace

logger = logging.getLogger(__name__)

LOCK_KEY = 7261153   # a fixed number: the Postgres lock for one run at a time


def run_once(session, writer=None) -> dict:
    from sqlalchemy import text

    from app.config import get_settings
    from app.services import feedback_loops, message_sender, zoho_fill

    s = get_settings()
    if not s.info_auto_fix_enabled:
        return {"skipped": "off (INFO_AUTO_FIX_ENABLED=false)"}
    if not message_sender.link_is_reachable(s.public_app_url):
        return {"skipped": "not the server (PUBLIC_APP_URL is not public) — "
                           "only the server edits the shared INFO sheet"}
    if not zoho_fill._is_eko(session):
        return {"skipped": "INFO is the Eko workspace's sheet"}
    lock = session.get_bind().connect()
    try:
        if not lock.execute(text("SELECT pg_try_advisory_lock(:k)"),
                            {"k": LOCK_KEY}).scalar():
            return {"skipped": "another INFO fix is still running"}
        try:
            return feedback_loops.auto_fix_info(session, s, writer=writer)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock.commit()
    finally:
        lock.close()


@celery_app.task(name="workers.fix_info", bind=True, max_retries=0)
@for_configured_workspace
def fix_info(self):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            result = run_once(session)
    finally:
        engine.dispose()
    if result.get("skipped"):
        logger.info("fix_info: nothing done — %s", result["skipped"])
    return result
