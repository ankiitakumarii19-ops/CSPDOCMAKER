"""
CSP DocMaker — alerts to the Super Admins (No. 173)

Every ALERT_MINUTES: services/alerts.py looks for a stuck or failing sheet
read, an agent failing again and again, or WhatsApps failing, and emails
the workspace's Super Admins — once per problem, again every
ALERT_REPEAT_HOURS while it lasts, once when it is fixed.

8 am – 8 pm (IST), one run at a time, never from a copy of the app that is
not on a public address. Off with ALERTS_ENABLED=false.
"""

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.workers.workspace_runner import for_each_workspace

logger = logging.getLogger(__name__)

LOCK_KEY = 7261173   # a fixed number: the Postgres lock for one run at a time


def run_once(session, now: datetime = None, send=None) -> dict:
    from sqlalchemy import text

    from app.config import get_settings
    from app.services import alerts, message_sender
    from app.workers.verify_old_csps_worker import in_hours

    s = get_settings()
    now = now or datetime.now(timezone.utc)
    if not s.alerts_enabled:
        return {"skipped": "off (ALERTS_ENABLED=false)"}
    if not message_sender.link_is_reachable(s.public_app_url):
        return {"skipped": "the app is not on a public address "
                           "(PUBLIC_APP_URL) — a laptop copy sends no alerts"}
    if not in_hours(now, s.verify_start_hour, s.verify_end_hour):
        return {"skipped": "outside sending hours"}
    send = send or (lambda to, subject, body:
                    message_sender._send_email(to, subject, body, kind="other"))
    lock = session.get_bind().connect()
    try:
        if not lock.execute(text("SELECT pg_try_advisory_lock(:k)"),
                            {"k": LOCK_KEY}).scalar():
            return {"skipped": "another alert run is still going"}
        try:
            return alerts.run(session, s, send, now=now)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock.commit()
    finally:
        lock.close()


@celery_app.task(name="workers.send_alerts", bind=True, max_retries=0)
@for_each_workspace
def send_alerts(self):
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
        logger.info("send_alerts: nothing done — %s", result["skipped"])
    return result
