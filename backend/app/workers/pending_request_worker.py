"""
CSP DocMaker — finish RM requests that were waiting for data

An RM only chooses a CSP and the documents (tracker No. 53). When details
are missing the request is kept as PENDING_DATA rather than failed, and the
CSP is asked for them. This task looks at every pending request after the
sheet has been synced; the moment nothing is missing for the documents the
RM chose, it makes them and sends them — the same pipeline, validation and
storage the automatic new-CSP path uses, so there is one way documents are
produced, not two.

Nothing is sent while anything is missing. A request still waiting is simply
looked at again next time.
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_each_workspace

logger = logging.getLogger(__name__)


@celery_app.task(
    name="workers.complete_pending_requests",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
@for_each_workspace
def complete_pending_requests(self):
    """Finish every pending RM request whose CSP now has every detail."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings

    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    try:
        with Session(engine) as session:
            return finish_ready(session)
    finally:
        engine.dispose()


def finish_ready(session) -> dict:
    """The work itself, separate from Celery so it can be tested directly."""
    from sqlalchemy import select

    from app.models.csp_record import CSPRecord
    from app.models.enums import DocumentType, JobState
    from app.models.processing_job import ProcessingJob
    from app.services.missing_data_service import check_missing_data
    from app.workers.new_csp_worker import _process_one, _try_photo

    pending = session.execute(
        select(ProcessingJob)
        .where(ProcessingJob.current_state == JobState.PENDING_DATA)
        .order_by(ProcessingJob.created_at)
    ).scalars().all()

    finished = waiting = failed = 0
    for job in pending:
        csp = session.execute(
            select(CSPRecord).where(CSPRecord.csp_id == job.csp_id)
        ).scalars().first()
        if csp is None:
            continue
        try:
            types = [DocumentType(v) for v in (job.requested_documents or [])]
        except ValueError:
            logger.error("pending_request_worker: job %s names an unknown "
                         "document type: %s", job.job_id,
                         job.requested_documents)
            continue
        if not types:
            continue

        if csp.origin == "new" and (
                csp.new_csp_processed_at is None
                or csp.new_csp_processed_at >= job.created_at):
            # A new CSP is sent all their documents by the automatic
            # new-CSP run. Finishing this request as well would email them
            # twice, so it waits for that run and is then closed by it. (A
            # run from BEFORE this request does not count: that CSP is
            # finished here like anyone else.)
            if csp.new_csp_processed_at is None:
                waiting += 1
                continue
            job.current_state = JobState.COMPLETED
            job.error_message = ("Sent by the automatic run for new CSPs.")
            session.commit()
            finished += 1
            continue

        try:
            # A missing photo may be in the CRM by now.
            if _try_photo(csp):
                session.commit()

            from app.services import photo_portrait
            photo_portrait.prepare_for(csp)
            from app.services import studio_photo
            studio_photo.prepare_for(csp)   # No. 72
            if check_missing_data(csp, types).has_missing_data:
                waiting += 1
                continue

            _process_one(session, csp, types, job=job)
            finished += 1
        except Exception as e:
            session.rollback()
            failed += 1
            logger.error("pending_request_worker: job %s for CSP %s failed: "
                         "%s: %s", job.job_id, job.csp_id,
                         type(e).__name__, e, exc_info=True)

    if pending:
        logger.info("pending_request_worker: %d pending — %d finished, %d "
                    "still waiting, %d failed", len(pending), finished,
                    waiting, failed)
    return {"pending": len(pending), "finished": finished,
            "waiting": waiting, "failed": failed}
