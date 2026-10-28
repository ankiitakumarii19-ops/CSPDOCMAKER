"""
CSP DocMaker — failed WhatsApps sent again (tracker No. 164)

Every RESEND_FAILED_MINUTES: a WhatsApp the platform failed to send is
tried again — 30 min, 1 h, 2 h, then every 4 h, for up to 7 days — until it
goes. Not when the number is not on WhatsApp (the contact loop's). What it
does: services/resend_failed.py.

Only between VERIFY_START_HOUR and VERIFY_END_HOUR (IST), like the other
messages to CSPs; one run at a time; never from a copy of the app that is
not on a public address (a laptop never messages a CSP). Off with
RESEND_FAILED_ENABLED=false.
"""

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.workers.workspace_runner import for_configured_workspace

logger = logging.getLogger(__name__)

LOCK_KEY = 7261164   # a fixed number: the Postgres lock for one run at a time


def run_once(session, now: datetime = None) -> dict:
    from sqlalchemy import text

    from app.config import get_settings
    from app.services import message_sender, resend_failed
    from app.workers.verify_old_csps_worker import in_hours

    s = get_settings()
    now = now or datetime.now(timezone.utc)
    if not s.resend_failed_enabled:
        return {"skipped": "off (RESEND_FAILED_ENABLED=false)"}
    if not message_sender.link_is_reachable(s.public_app_url):
        return {"skipped": "the app is not on a public address "
                           "(PUBLIC_APP_URL) — a laptop copy never messages "
                           "a CSP"}
    if not in_hours(now, s.verify_start_hour, s.verify_end_hour):
        return {"skipped": "outside sending hours"}
    lock = session.get_bind().connect()
    try:
        if not lock.execute(text("SELECT pg_try_advisory_lock(:k)"),
                            {"k": LOCK_KEY}).scalar():
            return {"skipped": "another resend run is still going"}
        try:
            return resend_failed.run(session, s, now=now)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock.commit()
    finally:
        lock.close()


@celery_app.task(name="workers.resend_failed", bind=True, max_retries=0)
@for_configured_workspace
def resend_failed(self):
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
        logger.info("resend_failed: nothing done — %s", result["skipped"])
    return result
