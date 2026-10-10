"""
CSP DocMaker — computing what a dashboard widget shows

The registry says which questions this product can answer. This answers
them.

Every function here is a deliberate query against the workspace in force.
Nothing takes SQL from configuration: a dashboard names a metric, and the
code for that metric lives here where it can be read and tested. A screen
that could describe its own query would be a screen that could read another
customer's data.

A metric returns one of three shapes, matching what the registry declares:

    scalar   {"value": 12, "drill": "..."}         one number
    series   [{"label": ..., "value": ...}, ...]   a breakdown
    rows     {"columns": [...], "rows": [...]}     a table
"""

import logging
from datetime import datetime, timezone
from typing import Callable, Dict

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.csp_record import CSPRecord
from app.models.data_request import DataRequest
from app.models.email_job import EmailJob
from app.models.enums import EmailStatus
from app.models.processing_job import ProcessingJob
from app.models.stored_document import StoredDocument
from app.services import document_registry as registry
from app.services import field_ownership as fo

logger = logging.getLogger(__name__)

_COMPUTERS: Dict[str, Callable] = {}


def computes(key: str):
    def register(fn):
        _COMPUTERS[key] = fn
        return fn
    return register


def is_computable(key: str) -> bool:
    return key in _COMPUTERS


async def compute(key: str, session: AsyncSession) -> dict:
    """Answer one metric, or say plainly that nothing answers it.

    A registered metric with no computer here is a bug, not a user error —
    it means a dashboard could be built that never renders.
    """
    fn = _COMPUTERS.get(key)
    if fn is None:
        raise KeyError(
            f"The metric {key!r} is registered but nothing computes it."
        )
    return await fn(session)


async def _count(session, statement) -> int:
    return int((await session.execute(statement)).scalar() or 0)


# ---- documents -----------------------------------------------------------

@computes("documents.generated")
async def _generated(session):
    # One CSP's document counts once however many versions it has.
    return {"value": await _count(session, select(
        func.count(distinct(func.concat(
            StoredDocument.csp_id, StoredDocument.document_type)))
    ))}


async def _csps_emailed(session, status=None) -> set:
    """Which CSPs an email was attempted for.

    An EmailJob names no CSP of its own — it belongs to a processing job,
    and that is what knows whose documents were being sent.
    """
    statement = (
        select(distinct(ProcessingJob.csp_id))
        .join(EmailJob, EmailJob.processing_job_id == ProcessingJob.id)
    )
    if status is not None:
        statement = statement.where(EmailJob.status == status)
    return set((await session.execute(statement)).scalars().all())


@computes("documents.mailed")
async def _mailed(session):
    return {"value": len(await _csps_emailed(session, EmailStatus.SENT))}


@computes("documents.failed")
async def _failed(session):
    """A CSP that failed and was later sent counts as sent, not failed."""
    sent = await _csps_emailed(session, EmailStatus.SENT)
    failed = await _csps_emailed(session, EmailStatus.FAILED)
    return {"value": len(failed - sent)}


@computes("documents.pending")
async def _pending(session):
    """Generated, but nothing has been sent for them yet."""
    have_documents = set((await session.execute(
        select(distinct(StoredDocument.csp_id))
    )).scalars().all())
    attempted = await _csps_emailed(session)
    return {"value": len(have_documents - attempted)}


@computes("documents.by_type")
async def _by_type(session):
    rows = (await session.execute(
        select(StoredDocument.document_type,
               func.count(distinct(StoredDocument.csp_id)))
        .group_by(StoredDocument.document_type)
    )).all()
    # The column still deserialises to a DocumentType for the supplied four
    # and to a plain string for anything uploaded. code_of flattens both to
    # the stored code, which is what the registry is keyed by.
    counts = {registry.code_of(code): n for code, n in rows}
    return [
        {"label": spec.name, "value": counts.get(spec.code, 0),
         "key": spec.code}
        for spec in registry.all_specs()
    ]


# ---- verification --------------------------------------------------------

@computes("verification.total")
async def _total(session):
    return {"value": await _count(session, select(func.count(CSPRecord.id)))}


@computes("verification.confirmed")
async def _confirmed(session):
    return {"value": await _count(session, select(
        func.count(distinct(DataRequest.csp_id))
    ).where(DataRequest.status == "answered"))}


@computes("verification.waiting_on_csp")
async def _waiting(session):
    now = datetime.now(timezone.utc)
    return {"value": await _count(session, select(
        func.count(distinct(DataRequest.csp_id))
    ).where(DataRequest.status == "open", DataRequest.expires_at > now))}


@computes("verification.expired")
async def _expired(session):
    now = datetime.now(timezone.utc)
    answered = select(DataRequest.csp_id).where(
        DataRequest.status == "answered")
    return {"value": await _count(session, select(
        func.count(distinct(DataRequest.csp_id))
    ).where(
        DataRequest.expires_at <= now,
        DataRequest.status.in_(("open", "expired")),
        DataRequest.csp_id.notin_(answered),
    ))}


@computes("verification.not_contacted")
async def _not_contacted(session):
    asked = select(DataRequest.csp_id)
    return {"value": await _count(session, select(
        func.count(CSPRecord.id)).where(CSPRecord.csp_id.notin_(asked)))}


@computes("verification.documents_held")
async def _documents_held(session):
    """Yes, No, and the people who were never asked.

    This used to report only the Yes count, which read as "nobody has an ID
    Card" when the truth was "one person said they do not and two were never
    asked". Those are different facts and lead to different work, so all
    three are shown and they add up to every CSP in the workspace.
    """
    total = await _count(session, select(func.count(CSPRecord.id)))
    rows = []
    for field in fo.DOCUMENTS_HELD:
        column = getattr(CSPRecord, field)
        yes = await _count(session, select(func.count(CSPRecord.id))
                           .where(func.lower(column) == "yes"))
        no = await _count(session, select(func.count(CSPRecord.id))
                          .where(func.lower(column) == "no"))
        rows.append({
            "key": field,
            "document": fo.held_document_name(field),
            "yes": yes,
            "no": no,
            "unanswered": max(total - yes - no, 0),
        })
    return {
        "columns": [
            {"key": "document", "label": "Document"},
            {"key": "yes", "label": "Yes"},
            {"key": "no", "label": "No"},
            {"key": "unanswered", "label": "Not answered"},
        ],
        "rows": rows,
    }


@computes("verification.recent_submissions")
async def _recent(session):
    rows = (await session.execute(
        select(DataRequest.csp_id, CSPRecord.name, DataRequest.answered_at,
               DataRequest.answered_values)
        .join(CSPRecord, CSPRecord.csp_id == DataRequest.csp_id)
        .where(DataRequest.status == "answered")
        .order_by(DataRequest.answered_at.desc())
        .limit(25)
    )).all()
    return {
        "columns": [
            {"key": "csp_id", "label": "CSP"},
            {"key": "name", "label": "Name"},
            {"key": "answered_at", "label": "Submitted"},
            {"key": "fields", "label": "Fields returned"},
        ],
        "rows": [
            {
                "csp_id": csp_id,
                "name": name or "",
                "answered_at": at.isoformat() if at else "",
                "fields": len(values or {}),
            }
            for csp_id, name, at, values in rows
        ],
    }


# ---- record completeness -------------------------------------------------

def _blank(field: str):
    column = getattr(CSPRecord, field)
    return (column.is_(None)) | (func.btrim(column) == "")


def _any_blank(fields):
    clause = None
    for field in fields:
        if not hasattr(CSPRecord, field):
            continue
        condition = _blank(field)
        clause = condition if clause is None else (clause | condition)
    return clause


@computes("data.missing_csp_details")
async def _missing_csp(session):
    clause = _any_blank(fo.CSP_OWNED)
    return {"value": await _count(
        session, select(func.count(CSPRecord.id)).where(clause))}


@computes("data.missing_org_details")
async def _missing_org(session):
    clause = _any_blank(fo.ORG_OWNED)
    return {"value": await _count(
        session, select(func.count(CSPRecord.id)).where(clause))}


@computes("data.complete")
async def _complete(session):
    clause = _any_blank(tuple(fo.CSP_OWNED) + tuple(fo.ORG_OWNED))
    return {"value": await _count(
        session, select(func.count(CSPRecord.id)).where(~clause))}


@computes("data.missing_photo")
async def _missing_photo(session):
    return {"value": await _count(
        session, select(func.count(CSPRecord.id)).where(_blank("photo_url")))}


@computes("data.awaiting_rm")
async def _awaiting_rm(session):
    from app.services.rm_resolution import UNRESOLVED

    return {"value": await _count(session, select(func.count(CSPRecord.id))
                                  .where(CSPRecord.rm_resolution == UNRESOLVED))}


def registered_computers() -> set:
    return set(_COMPUTERS)
