"""
CSP DocMaker — mark emails that bounced (tracker No. 127)

Every EMAIL_BOUNCE_MINUTES, Gmail's "delivery failed" notices from the last
3 days are read from the sending inbox (read-only: they stay unread) and the
emails they are about are marked bounced. The inbox serves every workspace,
so the matching is done across all of them.
"""

import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


def check_now() -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.services import email_log
    from app.workspace_context import all_workspaces

    s = get_settings()
    if s.email_method.lower().strip() != "smtp" or not (
            s.smtp_username and s.smtp_password):
        return {"checked": False,
                "reason": "email is not sent through an SMTP inbox here"}
    try:
        bounces = email_log.fetch_bounces()
    except Exception as e:
        logger.error("email_bounce_worker: could not read the inbox "
                     "(%s): %s: %s", s.imap_host, type(e).__name__, e,
                     exc_info=True)
        return {"checked": False, "reason": f"{type(e).__name__}: {e}"[:300]}
    engine = create_engine(s.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session, all_workspaces():
            marked = email_log.apply_bounces(session, bounces)
    finally:
        engine.dispose()
    logger.info("email_bounce_worker: %d notice(s), %d email(s) newly marked "
                "bounced", len(bounces), marked)
    return {"checked": True, "notices": len(bounces), "marked": marked}


@celery_app.task(name="workers.check_email_bounces", max_retries=0)
def check_email_bounces():
    return check_now()
