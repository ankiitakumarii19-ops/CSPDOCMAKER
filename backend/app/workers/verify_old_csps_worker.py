"""
CSP DocMaker — ask every old CSP to verify their details (tracker No. 126)

Asked for 21 Oct 2026: once the Calling sheet is in CSPDATA, WhatsApp all
the old CSPs to verify their details; mail them nothing. ONLY the CSPs
copied in from the Calling sheet — never one that was already in CSPDATA
before (told the same day) — and not those already emailed their documents
or already verified. On hold (Inactive / not live) never gets anything.

Pace (decided): VERIFY_BATCH_SIZE (25) every VERIFY_INTERVAL_MINUTES (15),
between VERIFY_START_HOUR and VERIFY_END_HOUR India time (8–20) — about 500
CSPs in 5 hours, without flooding Eko's shared WhatsApp number, and a
mistake is noticed after 25 messages, not 500. A batch stops after
VERIFY_STOP_AFTER sends in a row fail.

Each ask is message_sender.ask_for_details(verify=True): Zoho fills what it
can first (the address from the Address tab, else the Lead's Shop / Business
Address), the form shows every detail pre-filled. Sending it mails nothing;
once the CSP answers and the answer is in the sheet, they are enrolled for
their documents (csp_form_router._documents_after_verification, No. 134).

Runs only where the Calling sheet is connected (CALLING_SHEET_ID), i.e. on
the server, in the Eko workspace.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.workers.workspace_runner import for_configured_workspace

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
RECENTLY = timedelta(days=3)
LOCK_KEY = 7261126   # a fixed number: the Postgres lock for one batch at a time


def in_hours(now: datetime, start: int, end: int) -> bool:
    return start <= now.astimezone(IST).hour < end


def to_verify(session, limit: int) -> list:
    """The next old CSPs to ask, oldest code first."""
    from sqlalchemy import select

    from app.models.csp_record import CSPRecord
    from app.models.data_request import ANSWERED, DataRequest
    from app.models.email_job import EmailJob
    from app.models.enums import EmailStatus
    from app.models.processing_job import ProcessingJob

    from sqlalchemy import func

    from app.models.source_sheet import SourceSheetState

    # ONLY CSPs this app copied in from the Calling sheet (No. 121). A CSP
    # that was already in CSPDATA before — mailed or not — is never asked
    # (told 21 Oct 2026: "don't mail documents or WhatsApp verification to
    # the CSP data already present inside the sheet").
    copied_in = select(SourceSheetState.csp_code).where(
        SourceSheetState.imported_as == "baseline")
    emailed = (select(ProcessingJob.csp_id)
               .join(EmailJob, EmailJob.processing_job_id == ProcessingJob.id)
               .where(EmailJob.status == EmailStatus.SENT))
    verified = select(DataRequest.csp_id).where(DataRequest.status == ANSWERED)
    # Only an ask that actually reached the CSP counts (22 Oct 2026, No. 136):
    # one the WhatsApp platform failed or held back is retried next batch.
    recently = select(DataRequest.csp_id).where(
        DataRequest.created_at > datetime.now(timezone.utc) - RECENTLY,
        DataRequest.sent_to.isnot(None),
        DataRequest.delivery_error.is_(None))
    from app.services.message_sender import RETRY_FAILED_AFTER
    failed_just_now = select(DataRequest.csp_id).where(
        DataRequest.created_at > datetime.now(timezone.utc) - RETRY_FAILED_AFTER,
        DataRequest.delivery_error.isnot(None))
    return list(session.execute(
        select(CSPRecord).where(
            func.upper(CSPRecord.csp_id).in_(copied_in),
            CSPRecord.origin == "baseline",
            CSPRecord.send_hold.is_(None),
            CSPRecord.mobile.isnot(None), CSPRecord.mobile != "",
            CSPRecord.new_csp_processed_at.is_(None),
            CSPRecord.csp_id.not_in(emailed),
            CSPRecord.csp_id.not_in(verified),
            CSPRecord.csp_id.not_in(recently),
            CSPRecord.csp_id.not_in(failed_just_now))
        .order_by(CSPRecord.csp_id).limit(limit)).scalars().all())


def run_batch(session, now: datetime = None) -> dict:
    from app.config import get_settings

    s = get_settings()
    now = now or datetime.now(timezone.utc)
    if not in_hours(now, s.verify_start_hour, s.verify_end_hour):
        return {"skipped": "outside sending hours"}
    if s.verify_wait_for_address:
        # Address first, then verification (21 Oct 2026): the CSP's form
        # should show the address from the Address tab.
        from sqlalchemy import func, select

        from app.models.sync_run import SyncRun
        done = session.execute(select(func.count()).select_from(SyncRun).where(
            SyncRun.source == "address",
            SyncRun.status == "completed")).scalar()
        if not done:
            return {"skipped": "waiting for the Address tab to be read"}
    # One batch at a time (No. 136): two at once (a restart while one is
    # running) picked the same CSPs and messaged them twice.
    from sqlalchemy import text
    lock = session.get_bind().connect()
    try:
        if not lock.execute(text("SELECT pg_try_advisory_lock(:k)"),
                            {"k": LOCK_KEY}).scalar():
            return {"skipped": "another verification batch is still running"}
        try:
            return _send_batch(session, s)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"),
                         {"k": LOCK_KEY})
            lock.commit()
    finally:
        lock.close()


def _send_batch(session, s) -> dict:
    from app.services import message_sender

    batch = to_verify(session, s.verify_batch_size)
    sent, not_sent, failures_in_row = [], {}, 0
    for csp in batch:
        try:
            out = message_sender.ask_for_details(session, csp, verify=True)
        except (message_sender.NoChannel, message_sender.NoTemplate) as e:
            logger.error("verify_old_csps: cannot send at all — %s", e)
            return {"stopped": str(e), "sent": sent}
        except Exception as e:
            session.rollback()
            logger.error("verify_old_csps: %s failed: %s: %s", csp.csp_id,
                         type(e).__name__, e, exc_info=True)
            out = {"sent": False, "reason": type(e).__name__}
        if out.get("sent"):
            sent.append(csp.csp_id)
            failures_in_row = 0
        else:
            not_sent[csp.csp_id] = out.get("reason", "")
            failures_in_row += 1
            if failures_in_row >= s.verify_stop_after:
                logger.error("verify_old_csps: %d sends in a row failed "
                             "(last: %s) — batch stopped", failures_in_row,
                             out.get("reason"))
                break
    logger.info("verify_old_csps: asked %d, not asked %d", len(sent),
                len(not_sent))
    return {"sent": sent, "not_sent": not_sent}


@celery_app.task(name="workers.verify_old_csps", bind=True, max_retries=0)
@for_configured_workspace
def verify_old_csps(self):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings

    s = get_settings()
    if not (s.verify_old_csps_enabled and s.calling_sheet_id):
        return {"skipped": "off, or the Calling sheet is not connected"}
    engine = create_engine(s.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as session:
            return run_batch(session)
    finally:
        engine.dispose()
