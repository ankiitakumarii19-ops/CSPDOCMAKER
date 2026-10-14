"""
CSP DocMaker — New CSP Worker

Runs the whole flow for a newly detected CSP, unattended:

    fetch the photo from the CRM
      -> if anything is still missing, alert the RM and STOP
      -> otherwise generate, validate, convert to PDF, store both formats,
         and email the PDFs to the CSP
      -> stamp the CSP as processed so it never runs twice

Two rules shape this:

  * A document is produced only when every field AND the photograph are
    present. Nothing goes out with a placeholder face or a blank field; if
    anything is missing the RM is asked and the CSP waits.

  * Work is selected by ``(origin='new' OR auto_enrolled_at IS NOT NULL)
    AND new_csp_processed_at IS NULL``,
    never by a time window. An earlier version looked at CSPs created in the
    last few minutes, which meant any CSP added while the worker was down was
    skipped forever.

The processed stamp is written in the same transaction as the documents, and
the email is sent only after that commit succeeds, so a crash cannot send a
CSP their documents twice.
"""

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.workers.workspace_runner import for_each_workspace
from app import telemetry

logger = logging.getLogger(__name__)


@celery_app.task(
    name="workers.process_new_csps",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
@for_each_workspace
def process_new_csps(self):
    """Process every new CSP that has not been processed yet."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.models.csp_record import CSPRecord
    from app.models.enums import DocumentType
    from app.models.rm_alert import MISSING_DATA
    from app.services import alert_service
    from app.services.missing_data_service import check_missing_data

    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://")
    )

    all_doc_types = list(DocumentType)
    processed = alerted = failed = 0

    with Session(engine) as session:
        # Two kinds of work, both finished the same way:
        #
        #   a new CSP, which is automatic by definition; and
        #   an existing one an RM deliberately enrolled.
        #
        # A baseline CSP nobody enrolled is still never touched — that is
        # what stops a first sync emailing an entire organisation.
        from sqlalchemy import or_

        pending = session.execute(
            select(CSPRecord).where(
                or_(
                    CSPRecord.origin == "new",
                    CSPRecord.auto_enrolled_at.is_not(None),
                ),
                CSPRecord.new_csp_processed_at.is_(None),
            ).order_by(CSPRecord.created_at)
        ).scalars().all()

        if not pending:
            engine.dispose()
            return {"status": "nothing_to_do",
                    "timestamp": datetime.now(timezone.utc).isoformat()}

        logger.info("new_csp_worker: %d new CSP(s) awaiting processing",
                    len(pending))

        for csp in pending:
            try:
                if _try_photo(csp):
                    session.commit()

                from app.services import ko_level
                doc_types = ko_level.allowed_documents(
                    csp.csp_code or csp.csp_id, all_doc_types)
                from app.services import photo_portrait
                photo_portrait.prepare_for(csp)
                from app.services import studio_photo
                studio_photo.prepare_for(csp)   # No. 72
                missing = check_missing_data(csp, doc_types)
                if missing.has_missing_data:
                    message, details = alert_service.describe_missing(missing)
                    alert_service.raise_alert(
                        session, csp.csp_id, csp.rm_email,
                        MISSING_DATA, message, details,
                    )
                    session.commit()
                    alerted += 1
                    logger.info("new_csp_worker: CSP %s blocked — %s",
                                csp.csp_id, message)
                    continue

                _process_one(session, csp, doc_types)
                processed += 1

            except Exception as e:
                session.rollback()
                failed += 1
                logger.error(
                    "new_csp_worker: CSP %s failed: %s: %s",
                    csp.csp_id, type(e).__name__, e, exc_info=True,
                )

    engine.dispose()

    summary = {
        "status": "completed",
        "pending": len(pending),
        "documents_sent": processed,
        "rm_alerted": alerted,
        "failed": failed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        "new_csp_worker: %d new CSP(s) — %d completed, %d awaiting the RM, "
        "%d failed", len(pending), processed, alerted, failed,
    )
    return summary


def _try_photo(csp, from_crm: bool = True) -> bool:
    """Get the CSP's photo if we do not have one yet: from the CSP sheet's
    Photo column first (No. 99 — the picture staff put there), then from
    the CRM. `from_crm=False` skips the CRM, which downloads whole KYC packs
    and is too slow to wait for inside an RM's request.

    Returns True when the record was changed. A failure here is not an error:
    it simply leaves the photo missing, which the missing-data check then
    reports to the RM like any other absent field.
    """
    import os

    from app.services import csp_photo_service, sheet_photo_reader

    existing = (csp.photo_url or "").strip()
    if existing and os.path.isfile(existing):
        return False
    from app.services import csp_photo_store
    stored = csp_photo_store.original_path(csp)
    if stored:
        csp.photo_url = stored
        return False

    reasons = []
    sources = (sheet_photo_reader, csp_photo_service) if from_crm else (
        sheet_photo_reader,)
    for source in sources:
        result = source.fetch_photo(csp)
        if result.ok:
            csp.photo_url = result.path
            logger.info("new_csp_worker: CSP %s — %s", csp.csp_id,
                        result.message)
            return True
        reasons.append(result.message)

    logger.info("new_csp_worker: CSP %s — no photo: %s",
                csp.csp_id, " / ".join(reasons))
    return False


@telemetry.traced("issue_documents_for_csp", "new_csp_worker")
def _process_one(session, csp, document_types, job=None) -> None:
    """Generate, store and send one complete CSP's documents.

    `job` is an RM's request that was waiting for data (PENDING_DATA). When
    it is given, that job is finished; otherwise a new-CSP job is created.
    """
    import uuid

    from app.models.email_document import EmailDocument
    from app.models.email_job import EmailJob
    from app.models.enums import EmailStatus, JobState, WorkflowType
    from app.models.processing_job import ProcessingJob
    from app.services import (
        alert_service, csp_mapping, csp_photo_store, document_service,
        document_storage_service, document_validation_service,
        email_service, pdf_service,
    )
    from app.services.missing_data_service import DOCUMENT_LABELS

    # The automated run is a processing job like any other. Without this row
    # the admin dashboard — which counts jobs and emails — would show nothing
    # for CSPs handled automatically, understating what the system did.
    finishing_request = job is not None
    if finishing_request:
        job.current_state = JobState.DOCUMENT_GENERATING
        job.error_message = None
    else:
        job = ProcessingJob(
            job_id=f"JOB-{datetime.now(timezone.utc).strftime('%Y%m%d')}-"
                   f"{uuid.uuid4().hex[:6]}",
            csp_id=csp.csp_id,
            workflow_type=WorkflowType.NEW_CSP,
            current_state=JobState.DOCUMENT_GENERATING,
            requested_by=None,   # nobody asked: the sync detected the CSP
        )
        session.add(job)
    session.flush()

    made_on = csp_mapping.effective_certificate_date(csp)

    generated = document_service.generate_documents(
        csp, document_types, certificate_date_value=made_on)

    passed, results = document_validation_service.validate_all_documents(
        csp, generated, made_on)
    if not passed:
        # Validation failing is a defect in the templates or the data, not
        # something an RM can fix, so it is raised loudly and nothing is sent.
        job.current_state = JobState.FAILED_DOCUMENT_VALIDATION
        session.commit()
        raise RuntimeError(
            f"Document validation failed for CSP {csp.csp_id}: "
            f"{[r['issues'] for r in results if r['issues']]}"
        )

    converted = dict(pdf_service.convert_all([path for _, path in generated]))

    # Rows are built and added here rather than through
    # store_generated_documents(), which commits on its own: the stored files
    # and the processed stamp must land in ONE transaction, or a crash between
    # them would leave a CSP that looks unprocessed but already has documents,
    # and the next run would email them a second time.
    stored_rows = []
    for doc_type, docx_path in generated:
        version = document_storage_service.next_version(
            session, csp.csp_id, doc_type)
        row = document_storage_service.build_pdf_row(
            csp.csp_id, doc_type, converted[docx_path], version,
            processing_job_id=job.id)
        session.add(row)
        stored_rows.append(row)
        session.flush()
    # The photo (original + passport version) joins the record (No. 89).
    photo_changed = csp_photo_store.capture(session, csp)

    job.current_state = JobState.EMAIL_SENDING
    if not finishing_request:
        csp.new_csp_processed_at = datetime.now(timezone.utc)
    alert_service.resolve_alerts(session, csp.csp_id)
    session.commit()
    # Each PDF as a file in the CSP's folder too (No. 105). Never raises.
    from app.services import document_archive
    document_archive.save_all(
        (r.csp_id, r.document_type, r.version, r.file_data, csp.name)
        for r in stored_rows)
    if photo_changed:
        # ... and is shown in the CSP sheet (No. 91). Never raises.
        from app.services import sheet_photo
        from app.workspace_context import current_workspace_id
        sheet_photo.push(csp.csp_id, current_workspace_id())
    # Only the PDF is kept (No. 87); the working DOCX is no longer needed.
    document_storage_service.discard_working_files(
        [path for _, path in generated])

    pdf_paths = [converted[path] for _, path in generated]
    names = [DOCUMENT_LABELS.get(dt, dt.value) for dt, _ in generated]

    # Recorded before the attempt, so a failed send still says what it was
    # carrying. The email's status decides whether each document counts as
    # sent or failed.
    email_job = EmailJob(
        processing_job_id=job.id,
        recipient=csp.email,
        subject=f"Your CSP Documents — {csp.csp_id} | EKO India Financial Services",
        status=EmailStatus.SENDING,
    )
    email_job.documents = [
        EmailDocument(document_type=doc_type) for doc_type, _ in generated
    ]
    session.add(email_job)
    session.commit()

    sent = email_service.send_documents_email(
        to_email=csp.email,
        csp_name=csp.name,
        csp_id=csp.csp_id,
        doc_names=names,
        doc_filepaths=pdf_paths,
    )

    if sent:
        email_job.status = EmailStatus.SENT
        email_job.sent_at = datetime.now(timezone.utc)
        job.current_state = JobState.EMAIL_SENT
    else:
        email_job.status = EmailStatus.FAILED
        email_job.failure_reason = "Email provider did not accept the message."
        job.current_state = JobState.FAILED_EMAIL_SENDING
    session.commit()

    if sent:
        logger.info("new_csp_worker: CSP %s — %d document(s) sent to %s",
                    csp.csp_id, len(pdf_paths), csp.email)
        # And on WhatsApp, with the PDFs (No. 78). Never fails the delivery.
        from app.services import documents_whatsapp
        documents_whatsapp.notify(session, csp, job, names)
    else:
        # The documents are stored and the CSP stays processed; only delivery
        # failed, and that is an operational problem, not a reason to
        # regenerate and risk sending twice.
        logger.error(
            "new_csp_worker: CSP %s — documents stored but the email to %s "
            "was not accepted", csp.csp_id, csp.email,
        )
