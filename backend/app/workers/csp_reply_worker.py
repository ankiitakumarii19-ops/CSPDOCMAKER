"""
CSP DocMaker — the reply agent's run (tracker No. 151)

Every WHATSAPP_STATUS_MINUTES: reads what CSPs wrote on WhatsApp and writes
the replies (services/csp_replies.py). In "draft" mode they wait for a
person; in "auto" mode they are sent, but only between VERIFY_START_HOUR and
VERIFY_END_HOUR (IST). One run at a time; never from a copy of the app that
is not on a public address (a laptop never messages a CSP).
"""

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.workers.workspace_runner import for_configured_workspace

logger = logging.getLogger(__name__)

LOCK_KEY = 7261151   # a fixed number: the Postgres lock for one run at a time


def run_once(session, now: datetime = None, wa=None) -> dict:
    from sqlalchemy import text

    from app.config import get_settings
    from app.services import csp_replies, message_sender
    from app.workers.verify_old_csps_worker import in_hours

    s = get_settings()
    now = now or datetime.now(timezone.utc)
    if not message_sender.link_is_reachable(s.public_app_url):
        return {"skipped": "the app is not on a public address "
                           "(PUBLIC_APP_URL) — a laptop copy never messages "
                           "a CSP"}
    lock = session.get_bind().connect()
    try:
        if not lock.execute(text("SELECT pg_try_advisory_lock(:k)"),
                            {"k": LOCK_KEY}).scalar():
            return {"skipped": "another reply run is still going"}
        try:
            hours = in_hours(now, s.verify_start_hour, s.verify_end_hour)
            result = csp_replies.run(session, now=now, wa=wa,
                                     sending_hours=hours)
            # The day after the documents: "did you get them?" (No. 152).
            if hours:
                from app.services import documents_feedback
                result["feedback"] = documents_feedback.run(session, now=now,
                                                            wa=wa)
            return result
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock.commit()
    finally:
        lock.close()


@celery_app.task(name="workers.answer_csp_replies", bind=True, max_retries=0)
@for_configured_workspace
def answer_csp_replies(self):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            try:
                result = run_once(session)
            except Exception as e:
                session.rollback()
                logger.error("answer_csp_replies: the run failed: %s: %s",
                             type(e).__name__, e, exc_info=True)
                raise
    finally:
        engine.dispose()
    if result.get("skipped"):
        logger.info("answer_csp_replies: nothing done — %s", result["skipped"])
    return result
