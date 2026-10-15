"""
CSP DocMaker — keeping the WhatsApp messages screen current

Every WHATSAPP_STATUS_MINUTES (default 10), for each workspace: Meta's
delivered / read status of recent sends, the replies people sent back, the
forms filled in, and any of this app's sends found in the platform's history
but not yet on the record (tracker No. 110). The work is in
message_log.refresh; this only schedules it.
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_each_workspace

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.refresh_whatsapp_messages", bind=True)
@for_each_workspace
def refresh_whatsapp_messages(self):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.services import message_log

    engine = create_engine(
        get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            return message_log.refresh(session)
    finally:
        engine.dispose()
