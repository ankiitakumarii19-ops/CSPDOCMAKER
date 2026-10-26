"""
CSP DocMaker — the contact loop (tracker No. 150)

Every CONTACT_LOOP_MINUTES: a WhatsApp that did not reach the phone, or an
email that bounced, gets the CSP asked for the right number / address on
the other channel (once), and what failed is sent again once it is
corrected. What it does: services/feedback_loops.py.

Only between VERIFY_START_HOUR and VERIFY_END_HOUR (IST), like the other
messages to CSPs; one run at a time; never from a copy of the app that is
not on a public address (a laptop never messages a CSP). Off with
CONTACT_LOOP_ENABLED=false.
"""

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.workers.workspace_runner import for_configured_workspace

logger = logging.getLogger(__name__)

LOCK_KEY = 7261150   # a fixed number: the Postgres lock for one run at a time


def run_once(session, now: datetime = None) -> dict:
    from sqlalchemy import text

    from app.config import get_settings
    from app.services import feedback_loops, message_sender
    from app.workers.verify_old_csps_worker import in_hours

    s = get_settings()
    now = now or datetime.now(timezone.utc)
    if not s.contact_loop_enabled:
        return {"skipped": "off (CONTACT_LOOP_ENABLED=false)"}
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
            return {"skipped": "another contact-loop run is still going"}
        try:
            return feedback_loops.run(session, s, now=now)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock.commit()
    finally:
        lock.close()


@celery_app.task(name="workers.contact_loop", bind=True, max_retries=0)
@for_configured_workspace
def contact_loop(self):
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
        logger.info("contact_loop: nothing done — %s", result["skipped"])
    return result
