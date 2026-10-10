"""
CSP DocMaker — Workflow Router

Endpoints for the RM (existing CSP) document processing workflow:
  1. Check missing data → Generate → Validate → Prepare
  2. Confirm & Send (email documents to CSP)

CRITICAL RULE: Documents must NEVER be sent if validation fails.

Every step is persisted — ProcessingJob, DocumentJob, ValidationResult and
EmailJob rows are what the admin dashboard reports on.
"""

import shutil
import tempfile
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_session
from app.dependencies import require_role
from app.models.csp_record import CSPRecord
from app.models.document_job import DocumentJob
from app.models.email_job import EmailJob
from app.models.email_document import EmailDocument
from app.models.processing_job import ProcessingJob
from app.models.user import User
from app.models.validation_result import ValidationResult
from app.models.enums import (
    DocumentFormat,
    EmailStatus,
    JobState,
    ValidationStatus,
    ValidationType,
    WorkflowType,
)
from app.schemas.workflow import WorkflowProcessRequest
from app.services import csp_mapping
from app.services import csp_access
from app.services.missing_data_service import check_missing_data, DOCUMENT_LABELS
from app.services import document_service
from app.services import document_storage_service
from app.services import document_validation_service
from app.services import email_service
from app.services import pdf_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# Admins monitor only — generating and sending is an RM action.
require_rm = require_role("rm")


async def _get_requesting_user(session: AsyncSession, token_user: dict) -> User:
    """Resolve the JWT subject to the persisted User row."""
    email = token_user.get("sub")
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your account could not be found. Please log in again.",
        )
    return user


async def _get_owned_job(session: AsyncSession, job_id: str, user: User) -> ProcessingJob:
    """Load a job, allowing access only to the RM who requested it."""
    result = await session.execute(
        select(ProcessingJob).where(ProcessingJob.job_id == job_id)
    )
    job = result.scalar_one_or_none()
    # A job owned by someone else is reported exactly like a missing job so
    # job IDs cannot be probed.
    if job is None or job.requested_by != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )
    return job


@router.post(
    "/process",
    summary="Full workflow: check → generate → validate → prepare",
)
async def process_workflow(
    request: WorkflowProcessRequest,
    session: AsyncSession = Depends(get_session),
    token_user: dict = Depends(require_rm),
):
    """Execute the document processing workflow for an existing CSP.

    Steps:
      1. Validate CSP exists
      2. Check for missing data
      3. Generate documents
      4. Validate documents against source data
      5. Validate CSP email
      6. Park the job at awaiting_confirmation
    """
    user = await _get_requesting_user(session, token_user)
    csp_id = request.csp_id

    # 1. Find the CSP, restricted to what this RM may act on. A CSP owned by
    # another RM is reported exactly like a missing one.
    query = select(CSPRecord).where(CSPRecord.csp_id == csp_id)
    scope = csp_access.accessible_filter(token_user)
    if scope is not None:
        query = query.where(scope)
    csp = (await session.execute(query)).scalar_one_or_none()
    if not csp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CSP with ID '{csp_id}' not found.",
        )

    job_id = f"JOB-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
    job = ProcessingJob(
        job_id=job_id,
        csp_id=csp_id,
        workflow_type=WorkflowType.EXISTING_CSP,
        current_state=JobState.DATA_VALIDATING,
        requested_by=user.id,
    )
    session.add(job)
    await session.flush()

    # 2. Check for missing data
    missing_check = check_missing_data(csp, request.document_types)
    session.add(ValidationResult(
        processing_job_id=job.id,
        validation_type=ValidationType.DATA_VALIDATION,
        status=ValidationStatus.FAILED if missing_check.has_missing_data else ValidationStatus.PASSED,
        issues=missing_check.model_dump(mode="json") if missing_check.has_missing_data else None,
    ))
    if missing_check.has_missing_data:
        # The RM's part is done: they chose the CSP and the documents. The
        # missing details are the CSP's to supply (tracker No. 53), so the
        # request is KEPT, not failed, and finished automatically by
        # workers.complete_pending_requests once the sheet has the data.
        job.current_state = JobState.PENDING_DATA
        job.requested_documents = [dt.value for dt in request.document_types]
        job.error_message = (
            f"{missing_check.total_missing_fields} detail(s) missing — "
            f"waiting for the CSP.")
        await session.commit()
        return {
            "job_id": job_id,
            "csp_id": csp_id,
            "csp_name": csp.name,
            "status": "pending_data",
            "message": (
                "Some details are missing. The CSP will be asked for them on "
                "WhatsApp. The documents will be made and sent automatically "
                "once the details are in the sheet."),
            "missing_fields": sorted({
                f.field_label for d in missing_check.documents
                for f in d.missing_fields}),
            # The same detail the RM's card shows: what is missing, and for
            # which document. Read-only — the RM fills nothing.
            "missing_data": missing_check.model_dump(mode="json"),
            "ready_to_send": False,
        }

    # 3. Generate documents
    job.current_state = JobState.DOCUMENT_GENERATING
    await session.flush()
    # One date for the whole run: the documents and the check of them must
    # agree even if this crosses midnight. It is always today (No. 56).
    made_on = csp_mapping.effective_certificate_date(csp)
    try:
        generated = document_service.generate_documents(
            csp, request.document_types, certificate_date_value=made_on)
    except RuntimeError as e:
        job.current_state = JobState.FAILED_DOCUMENT_GENERATION
        job.error_message = "Document generation failed."
        job.error_details = str(e)[:5000]
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Document generation failed.", "job_id": job_id},
        )

    # 4. Validate documents
    job.current_state = JobState.DOCUMENT_VALIDATING
    await session.flush()
    all_passed, validation_results = document_validation_service.validate_all_documents(
        csp, generated, made_on,
    )
    for (doc_type, filepath), vr in zip(generated, validation_results):
        doc_status = ValidationStatus(vr["validation_status"])
        session.add(DocumentJob(
            processing_job_id=job.id,
            document_type=doc_type,
            generated_file_reference=filepath,
            validation_status=doc_status,
        ))
        session.add(ValidationResult(
            processing_job_id=job.id,
            validation_type=ValidationType.DETERMINISTIC,
            status=doc_status,
            issues={"document_type": doc_type.value, "issues": vr["issues"]},
        ))

    if not all_passed:
        job.current_state = JobState.FAILED_DOCUMENT_VALIDATION
        job.error_message = (
            "Document validation failed — documents do NOT match source data. "
            "Documents will NOT be sent."
        )
        await session.commit()
        return {
            "job_id": job_id,
            "csp_id": csp_id,
            "status": "failed_validation",
            "message": job.error_message,
            "validation_results": validation_results,
            "ready_to_send": False,
        }

    # 5. Convert to PDF and store both formats permanently.
    # Only validated documents get here, so nothing unchecked is ever stored
    # or sent. A conversion failure stops the workflow: the CSP is sent PDFs,
    # so a missing PDF means there is nothing to send.
    try:
        converted = pdf_service.convert_all([path for _, path in generated])
    except pdf_service.PDFConversionError as e:
        job.current_state = JobState.FAILED_PDF_CONVERSION
        job.error_message = "PDF conversion failed — documents will NOT be sent."
        job.error_details = str(e)[:5000]
        await session.commit()
        logger.error(
            "workflow_router.process: PDF conversion failed for CSP %s: %s",
            csp_id, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": job.error_message, "job_id": job_id},
        )

    pdf_by_docx = dict(converted)
    try:
        await document_storage_service.store_generated_documents_async(
            session=session,
            csp_id=csp.csp_id,
            pairs=[(doc_type, path, pdf_by_docx[path]) for doc_type, path in generated],
            processing_job_id=job.id,
        )
    except Exception as e:
        job.current_state = JobState.FAILED_PDF_CONVERSION
        job.error_message = "Storing the generated documents failed."
        job.error_details = str(e)[:5000]
        await session.commit()
        logger.error(
            "workflow_router.process: storing documents failed for CSP %s: %s",
            csp_id, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": job.error_message, "job_id": job_id},
        )

    # 6. Validate CSP email
    job.current_state = JobState.EMAIL_VALIDATING
    email_valid, email_error = document_validation_service.validate_csp_email(csp)
    session.add(ValidationResult(
        processing_job_id=job.id,
        validation_type=ValidationType.EMAIL_VALIDATION,
        status=ValidationStatus.PASSED if email_valid else ValidationStatus.FAILED,
        issues=None if email_valid else {"error": email_error},
    ))
    if not email_valid:
        job.current_state = JobState.FAILED_EMAIL_VALIDATION
        job.error_message = email_error
        await session.commit()
        return {
            "job_id": job_id,
            "csp_id": csp_id,
            "status": "failed_email_validation",
            "message": email_error,
            "ready_to_send": False,
        }

    # 7. Ready for confirmation
    job.current_state = JobState.AWAITING_CONFIRMATION
    await session.commit()

    return {
        "job_id": job_id,
        "csp_id": csp_id,
        "csp_name": csp.name,
        "status": "awaiting_confirmation",
        "documents_generated": len(generated),
        "document_types": [dt.value for dt, _ in generated],
        "document_labels": [DOCUMENT_LABELS.get(dt, dt.value) for dt, _ in generated],
        "validation_results": validation_results,
        "email_recipient": csp.email,
        "ready_to_send": True,
    }


@router.get(
    "/recent",
    summary="The requesting RM's own recent requests",
)
async def recent_requests(
    limit: int = 10,
    page: int = 1,
    session: AsyncSession = Depends(get_session),
    token_user: dict = Depends(require_rm),
):
    """This RM's request history, newest first.

    Scoped to the caller by requested_by — an RM's history is their own, and
    nothing here widens what they can see.

    Registered above /{job_id} on purpose: that route would otherwise match
    "recent" and look for a job of that name.
    """
    from sqlalchemy import func

    if page < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="page starts at 1.")
    limit = max(1, min(limit, 100))
    user = await _get_requesting_user(session, token_user)

    mine = ProcessingJob.requested_by == user.id
    total = (await session.execute(
        select(func.count()).select_from(ProcessingJob).where(mine)
    )).scalar() or 0

    jobs = (await session.execute(
        select(ProcessingJob).where(mine)
        .order_by(ProcessingJob.created_at.desc())
        .offset((page - 1) * limit).limit(limit)
    )).scalars().all()

    # The CSP names, in one query rather than one per row.
    csp_ids = {job.csp_id for job in jobs}
    names = dict((await session.execute(
        select(CSPRecord.csp_id, CSPRecord.name)
        .where(CSPRecord.csp_id.in_(csp_ids))
    )).all()) if csp_ids else {}

    return {
        "total": total,
        "page": page,
        "page_size": limit,
        "pages": max(1, -(-total // limit)),
        "requests": [
            {
                "job_id": job.job_id,
                "csp_id": job.csp_id,
                "csp_name": names.get(job.csp_id),
                "current_state": job.current_state.value,
                "workflow_type": job.workflow_type.value,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            }
            for job in jobs
        ],
    }


@router.get(
    "/{job_id}",
    summary="Get workflow status",
)
async def get_workflow_status(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    token_user: dict = Depends(require_rm),
):
    """Get the current status of one of the requesting RM's workflows."""
    user = await _get_requesting_user(session, token_user)
    job = await _get_owned_job(session, job_id, user)

    return {
        "job_id": job.job_id,
        "csp_id": job.csp_id,
        "current_state": job.current_state.value,
        "error_message": job.error_message,
        "retry_count": job.retry_count,
        "workflow_type": job.workflow_type.value,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.post(
    "/{job_id}/confirm",
    summary="Confirm & send documents to CSP",
)
async def confirm_and_send(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    token_user: dict = Depends(require_rm),
):
    """Confirm the documents and send them to the CSP's email.

    CRITICAL: This endpoint REFUSES to send documents if:
      - The job is not in 'awaiting_confirmation' state
      - Any of the job's documents did not pass validation or is missing on disk
      - CSP email validation did not pass
    """
    user = await _get_requesting_user(session, token_user)
    job = await _get_owned_job(session, job_id, user)

    if job.current_state != JobState.AWAITING_CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Job '{job_id}' is in state '{job.current_state.value}', "
                f"not 'awaiting_confirmation'. Cannot send documents."
            ),
        )

    csp_result = await session.execute(select(CSPRecord).where(CSPRecord.csp_id == job.csp_id))
    csp = csp_result.scalar_one_or_none()
    if not csp:
        job.current_state = JobState.FAILED_EMAIL_SENDING
        job.error_message = f"CSP '{job.csp_id}' not found in database."
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CSP '{job.csp_id}' not found.",
        )

    # Final email validation check
    email_valid, email_error = document_validation_service.validate_csp_email(csp)
    if not email_valid:
        job.current_state = JobState.FAILED_EMAIL_VALIDATION
        job.error_message = email_error
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Email validation failed: {email_error}",
        )

    # Send exactly the documents generated and validated for THIS job.
    documents = list(job.document_jobs)
    unvalidated = [
        d.document_type.value for d in documents
        if d.validation_status != ValidationStatus.PASSED
    ]
    if not documents or unvalidated:
        job.current_state = JobState.FAILED_EMAIL_SENDING
        job.error_message = (
            "The job's documents are missing or not validated"
            + (f": {', '.join(unvalidated)}" if unvalidated else ".")
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=job.error_message,
        )

    # The CSP receives PDFs, read back from permanent storage rather than from
    # disk: the generated files are working copies and may be gone by now.
    stored_pdfs = await document_storage_service.get_job_documents_async(
        session, job.id, DocumentFormat.PDF,
    )
    missing = {d.document_type for d in documents} - {
        p.document_type for p in stored_pdfs}
    if missing:
        job.current_state = JobState.FAILED_EMAIL_SENDING
        job.error_message = (
            "Stored PDFs are missing for: "
            + ", ".join(sorted(m.value for m in missing))
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=job.error_message,
        )

    corrupt = [p.filename for p in stored_pdfs
               if not document_storage_service.verify_integrity(p)]
    if corrupt:
        job.current_state = JobState.FAILED_EMAIL_SENDING
        job.error_message = (
            "Stored PDFs failed their checksum check: " + ", ".join(corrupt)
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=job.error_message,
        )

    attachment_dir = tempfile.mkdtemp(prefix=f"csp_send_{job.csp_id}_")
    doc_names = [
        DOCUMENT_LABELS.get(p.document_type, p.document_type.value)
        for p in stored_pdfs
    ]
    doc_files = [
        document_storage_service.write_to_disk(p, attachment_dir)
        for p in stored_pdfs
    ]
    subject = f"Your CSP Documents — {csp.csp_id} | EKO India Financial Services"

    email_job = EmailJob(
        processing_job_id=job.id,
        recipient=csp.email,
        subject=subject,
        status=EmailStatus.SENDING,
    )
    session.add(email_job)
    # Record which documents this email carries, before it is attempted. The
    # email's own status then decides whether each of them counts as sent or
    # failed — a failed send must still say what it was carrying.
    email_job.documents = [
        EmailDocument(document_type=doc_type)
        for doc_type in sorted({p.document_type for p in stored_pdfs},
                               key=lambda d: d.value)
    ]
    job.current_state = JobState.EMAIL_SENDING
    await session.flush()

    try:
        email_sent = email_service.send_documents_email(
            to_email=csp.email,
            csp_name=csp.name,
            csp_id=csp.csp_id,
            doc_names=doc_names,
            doc_filepaths=doc_files,
        )
    finally:
        # The attachments were written out of the database only to hand them
        # to the mailer; the stored copies remain the record.
        shutil.rmtree(attachment_dir, ignore_errors=True)

    if not email_sent:
        email_job.status = EmailStatus.FAILED
        email_job.failure_reason = "Email provider did not accept the message."
        job.current_state = JobState.FAILED_EMAIL_SENDING
        job.error_message = f"Email delivery to {csp.email} failed."
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send documents to {csp.email}.",
        )

    now = datetime.now(timezone.utc)
    email_job.status = EmailStatus.SENT
    email_job.sent_at = now
    # The CSP notification (WhatsApp) that follows a successful email is not
    # implemented yet, so the job stops at email_sent rather than claiming
    # the whole workflow is completed.
    job.current_state = JobState.EMAIL_SENT
    job.error_message = None
    await session.commit()

    logger.info(
        "workflow_router.confirm_and_send: documents sent for job %s (CSP %s)",
        job_id, job.csp_id,
    )

    return {
        "job_id": job_id,
        "csp_id": job.csp_id,
        "status": JobState.EMAIL_SENT.value,
        "message": f"Documents sent to {csp.email}.",
        "email_sent": True,
        "documents_sent": len(doc_files),
    }
