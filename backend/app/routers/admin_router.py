"""
CSP DocMaker — Admin Router

Endpoints for the admin dashboard: metrics and jobs monitoring.
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_session
from app.dependencies import require_role
from app.models.csp_record import CSPRecord
from app.models.processing_job import ProcessingJob
from app.models.document_job import DocumentJob
from app.models.email_job import EmailJob
from app.models.sms_job import SMSJob
from app.models.user import User
from app.models.audit_log import AuditLog
from app.models.enums import EmailStatus, JobState, SMSStatus
from app.services.missing_data_service import document_label

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get(
    "/dashboard",
    summary="Admin dashboard metrics",
)
async def get_dashboard(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Get dashboard metrics for the admin overview.

    Returns the 5 required cards plus additional operational metrics:
      1. Total CSPs
      2. New CSPs Onboarded Today
      3. Documents Generated Today
      4. Emails Sent
      5. Failed Emails
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. Total CSPs
    total_csps_result = await session.execute(
        select(func.count()).select_from(CSPRecord)
    )
    total_csps = total_csps_result.scalar() or 0

    # 2. New CSPs Onboarded Today
    new_csps_result = await session.execute(
        select(func.count()).select_from(CSPRecord).where(
            CSPRecord.created_at >= today_start
        )
    )
    new_csps_today = new_csps_result.scalar() or 0

    # 3. Documents Generated Today (count of document jobs created today)
    docs_generated_result = await session.execute(
        select(func.count()).select_from(DocumentJob).where(
            DocumentJob.created_at >= today_start
        )
    )
    documents_generated_today = docs_generated_result.scalar() or 0

    # 4. Emails Sent Today (completed email jobs)
    emails_sent_result = await session.execute(
        select(func.count()).select_from(EmailJob).where(
            and_(
                EmailJob.created_at >= today_start,
                EmailJob.status == EmailStatus.SENT,
            )
        )
    )
    emails_sent_today = emails_sent_result.scalar() or 0

    # 5. Failed Emails Today
    failed_emails_result = await session.execute(
        select(func.count()).select_from(EmailJob).where(
            and_(
                EmailJob.created_at >= today_start,
                EmailJob.status == EmailStatus.FAILED,
            )
        )
    )
    failed_emails_today = failed_emails_result.scalar() or 0

    # SMS failures today
    sms_failures_result = await session.execute(
        select(func.count()).select_from(SMSJob).where(
            and_(
                SMSJob.created_at >= today_start,
                SMSJob.status == SMSStatus.FAILED,
            )
        )
    )
    sms_failures_today = sms_failures_result.scalar() or 0

    # Additional metrics
    # Document validation failures
    doc_validation_failures_result = await session.execute(
        select(func.count()).select_from(ProcessingJob).where(
            and_(
                ProcessingJob.created_at >= today_start,
                ProcessingJob.current_state == JobState.FAILED_DOCUMENT_VALIDATION,
            )
        )
    )
    doc_validation_failures = doc_validation_failures_result.scalar() or 0

    # Email validation failures
    email_validation_failures_result = await session.execute(
        select(func.count()).select_from(ProcessingJob).where(
            and_(
                ProcessingJob.created_at >= today_start,
                ProcessingJob.current_state == JobState.FAILED_EMAIL_VALIDATION,
            )
        )
    )
    email_validation_failures = email_validation_failures_result.scalar() or 0

    # Processing failures
    processing_failures_result = await session.execute(
        select(func.count()).select_from(ProcessingJob).where(
            and_(
                ProcessingJob.created_at >= today_start,
                ProcessingJob.current_state.in_([
                    JobState.FAILED_DOCUMENT_GENERATION,
                    JobState.FAILED_EMAIL_SENDING,
                    JobState.FAILED_DATA_VALIDATION,
                ]),
            )
        )
    )
    processing_failures = processing_failures_result.scalar() or 0

    # Pending and running jobs
    pending_jobs_result = await session.execute(
        select(func.count()).select_from(ProcessingJob).where(
            # Jobs waiting between steps (including RM confirmation)
            ProcessingJob.current_state.in_([
                JobState.DETECTED,
                JobState.DATA_VALIDATED,
                JobState.DOCUMENT_GENERATED,
                JobState.DOCUMENT_VALIDATED,
                JobState.EMAIL_VALIDATED,
                JobState.READY_TO_SEND,
                JobState.AWAITING_CONFIRMATION,
                # An RM request waiting for the CSP's details (No. 53).
                JobState.PENDING_DATA,
            ])
        )
    )
    pending_jobs = pending_jobs_result.scalar() or 0

    running_jobs_result = await session.execute(
        select(func.count()).select_from(ProcessingJob).where(
            ProcessingJob.current_state.in_([
                JobState.DATA_VALIDATING,
                JobState.DOCUMENT_GENERATING,
                JobState.DOCUMENT_VALIDATING,
                JobState.EMAIL_VALIDATING,
                JobState.EMAIL_SENDING,
                JobState.SMS_SENDING,
            ])
        )
    )
    running_jobs = running_jobs_result.scalar() or 0

    # Successful workflows today
    successful_result = await session.execute(
        select(func.count()).select_from(ProcessingJob).where(
            and_(
                ProcessingJob.created_at >= today_start,
                ProcessingJob.current_state == JobState.COMPLETED,
            )
        )
    )
    successful_workflows = successful_result.scalar() or 0

    # Failed workflows today (all failure states)
    failed_result = await session.execute(
        select(func.count()).select_from(ProcessingJob).where(
            and_(
                ProcessingJob.created_at >= today_start,
                ProcessingJob.current_state.in_([
                    JobState.FAILED_DATA_VALIDATION,
                    JobState.FAILED_DOCUMENT_GENERATION,
                    JobState.FAILED_DOCUMENT_VALIDATION,
                    JobState.FAILED_EMAIL_VALIDATION,
                    JobState.FAILED_EMAIL_SENDING,
                    JobState.FAILED_SMS_SENDING,
                ]),
            )
        )
    )
    failed_workflows = failed_result.scalar() or 0

    # Total retries today
    retries_result = await session.execute(
        select(func.sum(ProcessingJob.retry_count)).select_from(ProcessingJob).where(
            ProcessingJob.created_at >= today_start
        )
    )
    total_retries = retries_result.scalar() or 0

    # Last successful automation
    last_success_result = await session.execute(
        select(ProcessingJob.updated_at)
        .where(ProcessingJob.current_state == JobState.COMPLETED)
        .order_by(ProcessingJob.updated_at.desc())
        .limit(1)
    )
    last_success = last_success_result.scalar_one_or_none()

    return {
        "metrics": {
            "total_csps": total_csps,
            "new_csps_today": new_csps_today,
            "documents_generated_today": documents_generated_today,
            "emails_sent_today": emails_sent_today,
            "failed_emails_today": failed_emails_today,
            "document_validation_failures_today": doc_validation_failures,
            "email_validation_failures_today": email_validation_failures,
            "sms_failures_today": sms_failures_today,
            "processing_failures_today": processing_failures,
            "pending_jobs": pending_jobs,
            "running_jobs": running_jobs,
            "successful_workflows_today": successful_workflows,
            "failed_workflows_today": failed_workflows,
            "total_retries_today": total_retries,
            "last_successful_automation": (
                last_success.isoformat() if last_success else None
            ),
        },
    }


@router.get(
    "/jobs",
    summary="Paginated job list",
)
async def get_jobs(
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Get a paginated list of processing jobs."""
    offset = (page - 1) * page_size

    # Total count
    total_result = await session.execute(
        select(func.count()).select_from(ProcessingJob)
    )
    total = total_result.scalar() or 0

    # Fetch page
    stmt = (
        select(ProcessingJob, User.email)
        .outerjoin(User, User.id == ProcessingJob.requested_by)
        .order_by(ProcessingJob.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    rows = result.all()

    return {
        "jobs": [
            {
                "job_id": job.job_id,
                "csp_id": job.csp_id,
                "workflow_type": job.workflow_type.value,
                "current_state": job.current_state.value,
                "error_message": job.error_message,
                "retry_count": job.retry_count,
                # NULL requested_by = system-initiated (automated new-CSP) job
                "requested_by": requester_email,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            }
            for job, requester_email in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/audit-logs",
    summary="Paginated audit logs",
)
async def get_audit_logs(
    page: int = 1,
    page_size: int = 50,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Get paginated audit log entries."""
    offset = (page - 1) * page_size

    total_result = await session.execute(
        select(func.count()).select_from(AuditLog)
    )
    total = total_result.scalar() or 0

    stmt = (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.user_id)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    rows = result.all()

    return {
        "entries": [
            {
                "id": str(entry.id),
                # NULL user_id = system-initiated event
                "actor_email": actor_email,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "csp_id": entry.csp_id,
                "result": entry.result,
                "metadata": entry.metadata_json,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry, actor_email in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# CSP-centric metrics
#
# The dashboard above counts jobs. Admins monitor CSPs: how many exist, how
# many are new versus already on the books, which of them actually have each
# document, and who is still waiting on an RM. Everything here is derived
# from what is stored, never from a job's claimed state, so a document counts
# only once its bytes are in the database.
# ---------------------------------------------------------------------------

# Columns an admin can filter by. Circle Head is deliberately absent: it is
# not a CSP column and no document carries one.
# ---- drill-down scoping -------------------------------------------------

# Every required field of every document, plus the photo: a CSP counts as
# "details fetched" only when all of them are present. Computed in Python
# rather than SQL because required_fields() is the single definition of what
# a document needs, and duplicating it in a query would let the two drift.
def _details_complete(csp) -> bool:
    from app.models.enums import DocumentType
    from app.services.missing_data_service import check_missing_data
    return not check_missing_data(csp, list(DocumentType)).has_missing_data


def _parse_day(value: str | None, field: str):
    """'2026-09-28' → an aware datetime at the start of that UTC day."""
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} must be a date in YYYY-MM-DD form, not '{value}'.",
        )
    return parsed.replace(tzinfo=timezone.utc)


def _apply_dates(query, column, date_from: str | None, date_to: str | None):
    """Inclusive of both days: date_to covers everything up to its midnight."""
    start = _parse_day(date_from, "date_from")
    end = _parse_day(date_to, "date_to")
    if start and end and end < start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to cannot be before date_from.",
        )
    if start:
        query = query.where(column >= start)
    if end:
        query = query.where(column < end + timedelta(days=1))
    return query


FILTER_FIELDS = {
    "rm": CSPRecord.rm_name,
    "dc": CSPRecord.dc,
    "ao": CSPRecord.ao,
    "asm": CSPRecord.asm_name,
    "ch": CSPRecord.circle_head,
    "lho": CSPRecord.lho,
    "district": CSPRecord.district,
    "state": CSPRecord.state,
}


def _apply_filters(query, filters: dict):
    for name, value in filters.items():
        column = FILTER_FIELDS.get(name)
        if column is not None and value:
            query = query.where(column == value)
    return query


@router.get("/csp-metrics", summary="CSP counts, per document and per filter")
async def csp_metrics(
    rm: str | None = None,
    dc: str | None = None,
    ao: str | None = None,
    asm: str | None = None,
    ch: str | None = None,
    lho: str | None = None,
    district: str | None = None,
    state: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """New vs existing CSPs, and how many of each hold every document."""
    from app.models.enums import DocumentFormat, DocumentType
    from app.models.rm_alert import OPEN, RMAlert
    from app.models.stored_document import StoredDocument

    filters = {"rm": rm, "dc": dc, "ao": ao, "asm": asm, "ch": ch,
               "lho": lho, "district": district, "state": state}
    active = {k: v for k, v in filters.items() if v}

    # Which CSPs are in scope, as a reusable subquery.
    scoped_query = _apply_filters(
        select(CSPRecord.csp_id, CSPRecord.origin), active)
    scoped_query = _apply_dates(
        scoped_query, CSPRecord.created_at, date_from, date_to)
    scoped = scoped_query.subquery()

    totals = (await session.execute(
        select(scoped.c.origin, func.count()).group_by(scoped.c.origin)
    )).all()
    by_origin = {origin or "unknown": count for origin, count in totals}
    total = sum(by_origin.values())

    scoped_ids = set((await session.execute(
        select(scoped.c.csp_id))).scalars().all())

    # A document counts when its PDF is stored — that is the copy a CSP is
    # sent, so it is the only honest measure of "done".
    per_document = []
    for doc_type in DocumentType:
        rows = (await session.execute(
            select(scoped.c.origin, func.count(func.distinct(StoredDocument.csp_id)))
            .select_from(scoped)
            .join(StoredDocument, StoredDocument.csp_id == scoped.c.csp_id)
            .where(
                StoredDocument.document_type == doc_type,
                StoredDocument.file_format == DocumentFormat.PDF,
            )
            .group_by(scoped.c.origin)
        )).all()
        counts = {origin or "unknown": count for origin, count in rows}
        done = sum(counts.values())

        # Delivery, per document and scoped to the current filters. The
        # three buckets partition the population: mailed, failed (and not
        # since mailed), and everything else still pending.
        mailed_ids, failed_ids = await _delivery_sets(session, doc_type)
        # Only the CSPs this document is for: a Sub-KO never gets a BCP
        # (No. 57), so it is not "pending" one either.
        from app.services import ko_level
        eligible = {i for i in scoped_ids
                    if ko_level.allowed_documents(i, [doc_type])}
        mailed = len(eligible & mailed_ids)
        failed = len(eligible & failed_ids)

        per_document.append({
            "document_type": doc_type.value,
            "label": document_label(doc_type),
            "new": counts.get("new", 0),
            "existing": counts.get("baseline", 0),
            "generated": done,
            "mailed": mailed,
            "failed": failed,
            "pending": max(len(eligible) - mailed - failed, 0),
        })

    waiting = (await session.execute(
        select(func.count(func.distinct(RMAlert.csp_id)))
        .select_from(scoped)
        .join(RMAlert, RMAlert.csp_id == scoped.c.csp_id)
        .where(RMAlert.status == OPEN)
    )).scalar() or 0

    # "Details fetched" = every required field of every document present,
    # photo included. Evaluated on the records themselves so the dashboard
    # and the drill-down behind it can never disagree.
    in_scope = (await session.execute(
        select(CSPRecord).where(CSPRecord.csp_id.in_(select(scoped.c.csp_id)))
    )).scalars().all()
    complete = sum(1 for c in in_scope if _details_complete(c))

    return {
        "filters_applied": active,
        "date_from": date_from,
        "date_to": date_to,
        "totals": {
            "csps": total,
            "new": by_origin.get("new", 0),
            "existing": by_origin.get("baseline", 0),
            "awaiting_rm": waiting,
            "details_fetched": complete,
            "details_missing": max(total - complete, 0),
        },
        "documents": per_document,
    }


@router.get("/csp-filters", summary="Values available in each filter")
async def csp_filters(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Distinct values actually present, so a filter can never return zero."""
    options: dict[str, list[str]] = {}
    for name, column in FILTER_FIELDS.items():
        rows = (await session.execute(
            select(column).where(column.isnot(None), column != "").distinct()
            .order_by(column)
        )).scalars().all()
        options[name] = [r for r in rows if r]
    return {"filters": options}


# ---- per-document delivery --------------------------------------------

def _delivery_subquery(doc_type, status):
    """CSP ids whose email carrying `doc_type` reached `status`.

    email_documents is what makes this per document: one email carries a
    whole job's documents, so the email's status alone could only answer
    per job.
    """
    from app.models.email_document import EmailDocument

    return (
        select(ProcessingJob.csp_id)
        .join(EmailJob, EmailJob.processing_job_id == ProcessingJob.id)
        .join(EmailDocument, EmailDocument.email_job_id == EmailJob.id)
        .where(EmailDocument.document_type == doc_type,
               EmailJob.status == status)
    )


async def _delivery_sets(session, doc_type):
    """(mailed, failed) CSP-id sets, as one CSP per bucket.

    A CSP that failed and was later mailed counts as mailed only, so the
    three buckets partition the population and the numbers on screen add
    up to the total.
    """
    mailed = set((await session.execute(
        _delivery_subquery(doc_type, EmailStatus.SENT))).scalars().all())
    failed = set((await session.execute(
        _delivery_subquery(doc_type, EmailStatus.FAILED))).scalars().all())
    return mailed, failed - mailed


DELIVERY_VIEWS = ("mailed", "pending", "failed")

DRILL_VIEWS = ("new", "existing", "awaiting_rm",
               "details_fetched", "details_missing")


async def _drill_rows(session, params: dict):
    """Everything the drill-down needs, before paging.

    Returns (rows, total). Views that depend on required-field completeness
    are filtered in Python — see _details_complete — so paging is applied
    after filtering, never before, or a page could come back short.
    """
    from app.models.enums import DocumentFormat, DocumentType
    from app.models.rm_alert import OPEN, RMAlert
    from app.models.stored_document import StoredDocument

    view = params.get("view")
    if view and view not in DRILL_VIEWS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown view '{view}'. Expected one of: "
                   + ", ".join(DRILL_VIEWS),
        )

    active = {k: v for k, v in params["filters"].items() if v}
    query = _apply_filters(select(CSPRecord), active)
    query = _apply_dates(query, CSPRecord.created_at,
                         params.get("date_from"), params.get("date_to"))

    if view == "new":
        query = query.where(CSPRecord.origin == "new")
    elif view == "existing":
        query = query.where(CSPRecord.origin == "baseline")
    elif view == "awaiting_rm":
        query = query.where(CSPRecord.csp_id.in_(
            select(RMAlert.csp_id).where(RMAlert.status == OPEN)))

    document_type = params.get("document_type")
    delivery = params.get("delivery")
    if delivery and delivery not in DELIVERY_VIEWS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown delivery '{delivery}'. Expected one of: "
                   + ", ".join(DELIVERY_VIEWS),
        )
    if delivery and not document_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="delivery needs a document_type to be about.",
        )

    doc_type = None
    if document_type:
        try:
            doc_type = DocumentType(document_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown document type '{document_type}'.",
            )
        if not delivery:
            holders = select(StoredDocument.csp_id).where(
                StoredDocument.document_type == doc_type,
                StoredDocument.file_format == DocumentFormat.PDF,
            )
            query = query.where(
                CSPRecord.csp_id.notin_(holders) if params.get("missing")
                else CSPRecord.csp_id.in_(holders)
            )

    records = list((await session.execute(
        query.order_by(CSPRecord.created_at.desc())
    )).scalars().all())

    if delivery:
        # The same sets the dashboard counted with, so a tile and the list
        # behind it can never disagree.
        mailed_ids, failed_ids = await _delivery_sets(session, doc_type)
        if delivery == "mailed":
            records = [c for c in records if c.csp_id in mailed_ids]
        elif delivery == "failed":
            records = [c for c in records if c.csp_id in failed_ids]
        else:   # pending — neither mailed nor failed
            records = [c for c in records
                       if c.csp_id not in mailed_ids
                       and c.csp_id not in failed_ids]

    if view == "details_fetched":
        records = [c for c in records if _details_complete(c)]
    elif view == "details_missing":
        records = [c for c in records if not _details_complete(c)]

    return records, len(records)


def _drill_row(csp) -> dict:
    return {
        "csp_id": csp.csp_id,
        "name": csp.name,
        "origin": csp.origin,
        "district": csp.district,
        "state": csp.state,
        "lho": csp.lho,
        "rm_name": csp.rm_name,
        "rm_resolution": csp.rm_resolution,
        "circle_head": csp.circle_head,
    }


@router.get("/csp-list", summary="CSPs behind the numbers")
async def csp_list(
    rm: str | None = None,
    dc: str | None = None,
    ao: str | None = None,
    asm: str | None = None,
    ch: str | None = None,
    lho: str | None = None,
    district: str | None = None,
    state: str | None = None,
    document_type: str | None = None,
    view: str | None = None,
    delivery: str | None = None,
    missing: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 25,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """The drill-down: which CSPs make up a number on the dashboard.

    With document_type, `missing=false` lists the CSPs that have it and
    `missing=true` those that do not — which is what an admin chasing a gap
    actually wants. `view` selects one of the dashboard's own tiles instead.
    """
    if page < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="page starts at 1.")
    page_size = max(1, min(page_size, 200))

    filters = {"rm": rm, "dc": dc, "ao": ao, "asm": asm, "ch": ch,
               "lho": lho, "district": district, "state": state}
    records, total = await _drill_rows(session, {
        "filters": filters, "document_type": document_type, "view": view,
        "delivery": delivery,
        "missing": missing, "date_from": date_from, "date_to": date_to,
    })

    offset = (page - 1) * page_size
    window = records[offset:offset + page_size]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
        "csps": [_drill_row(c) for c in window],
    }


@router.get("/csp-list.csv", summary="The same drill-down, as a CSV file")
async def csp_list_csv(
    rm: str | None = None,
    dc: str | None = None,
    ao: str | None = None,
    asm: str | None = None,
    ch: str | None = None,
    lho: str | None = None,
    district: str | None = None,
    state: str | None = None,
    document_type: str | None = None,
    view: str | None = None,
    delivery: str | None = None,
    missing: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Export exports what is on screen — every matching row, unpaged."""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    filters = {"rm": rm, "dc": dc, "ao": ao, "asm": asm, "ch": ch,
               "lho": lho, "district": district, "state": state}
    records, _ = await _drill_rows(session, {
        "filters": filters, "document_type": document_type, "view": view,
        "delivery": delivery,
        "missing": missing, "date_from": date_from, "date_to": date_to,
    })

    columns = ["csp_id", "name", "origin", "district", "state", "lho",
               "rm_name", "rm_resolution", "circle_head"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for csp in records:
        writer.writerow({k: (v if v is not None else "")
                         for k, v in _drill_row(csp).items()})

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    logger.info("admin_router.csp_list_csv: exported %d row(s)", len(records))
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="csps-{stamp}.csv"'},
    )


# ---- one CSP, found from the top-bar search (No. 101) ------------------

@router.get("/csp/{csp_id}/summary",
            summary="One CSP's details and where each document stands")
async def csp_summary(
    csp_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """What the admin search opens: the CSP's details and, per document,
    whether it was made and whether it was mailed. Read-only.

    Delivery is decided by the same queries the dashboard counts with, so
    this panel and the numbers can never disagree.
    """
    from app.models.enums import DocumentFormat, DocumentType
    from app.models.stored_document import StoredDocument
    from app.schemas.csp import CSPDetailResponse
    from app.services import ko_level

    csp = (await session.execute(
        select(CSPRecord).where(CSPRecord.csp_id == csp_id)
    )).scalar_one_or_none()
    if csp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"CSP '{csp_id}' not found.")

    stored = (await session.execute(
        select(StoredDocument.document_type,
               func.max(StoredDocument.version),
               func.max(StoredDocument.created_at))
        .where(StoredDocument.csp_id == csp_id,
               StoredDocument.file_format == DocumentFormat.PDF)
        .group_by(StoredDocument.document_type)
    )).all()
    made = {t: (version, created) for t, version, created in stored}

    documents = []
    for doc_type in DocumentType:
        applies = bool(ko_level.allowed_documents(
            csp.csp_code or csp.csp_id, [doc_type]))
        mailed = (await session.execute(
            _delivery_subquery(doc_type, EmailStatus.SENT)
            .where(ProcessingJob.csp_id == csp_id).limit(1))).first()
        failed = (await session.execute(
            _delivery_subquery(doc_type, EmailStatus.FAILED)
            .where(ProcessingJob.csp_id == csp_id).limit(1))).first()
        version, created = made.get(doc_type, (None, None))
        documents.append({
            "document_type": doc_type.value,
            "label": document_label(doc_type),
            "applies": applies,
            "generated": doc_type in made,
            "version": version,
            "generated_at": created.isoformat() if created else None,
            # A CSP that failed and was later mailed counts as mailed, as on
            # the dashboard.
            "delivery": ("not_for_this_csp" if not applies
                         else "mailed" if mailed
                         else "failed" if failed
                         else "pending"),
        })

    return {
        "csp": CSPDetailResponse.model_validate(csp).model_dump(mode="json"),
        "documents": documents,
    }
