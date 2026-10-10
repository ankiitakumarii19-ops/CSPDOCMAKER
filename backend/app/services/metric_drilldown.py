"""
CSP DocMaker — the records behind a number

A dashboard says "Missing own details: 2". The useful next question is
always *which two*, and until now the only way to answer it was to go and
look. This turns every drillable metric into a list.

Two rules shape it.

**The list must agree with the number.** A tile that says 2 and opens a
list of 3 is worse than a tile that does not open at all, because it makes
every other number on the screen suspect. So each metric's membership is
defined once, here, and `test_metric_drilldown` asserts that the count the
dashboard shows equals the length of the list this returns — for every
drillable metric, so a new one cannot be added without the two agreeing.

**The list must say why.** Knowing that a CSP is missing their own details
is only half an answer; the RM still has to find out which fields. For the
completeness metrics the blank fields are named in the row.

Nothing here constructs its own SQL from user input: a metric key selects
one of the clauses below and nothing else, so a drill-down cannot be
steered into reading something it should not. Workspace scoping is applied
underneath by the session, exactly as it is for the counts.
"""

import logging
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

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
from app.services import metric_compute as mc

logger = logging.getLogger(__name__)

# A drill-down is a list to read, not an export. Past this, the answer is
# "filter it down" rather than a longer page.
MAX_ROWS = 500

_FINDERS: Dict[str, Callable] = {}


def finds(key: str):
    def register(fn):
        _FINDERS[key] = fn
        return fn
    return register


def is_drillable(key: str) -> bool:
    return key in _FINDERS


def drillable_keys() -> set:
    return set(_FINDERS)


# ---- the columns a drill-down shows -------------------------------------

CSP_COLUMNS = [
    {"key": "csp_code", "label": "CSP code"},
    {"key": "name", "label": "Name"},
    {"key": "branch_name", "label": "Branch"},
    {"key": "rm_name", "label": "RM"},
]
MISSING_COLUMN = {"key": "missing", "label": "What is missing"}


def _csp_row(csp: CSPRecord) -> dict:
    return {
        "csp_id": csp.csp_id,
        "csp_code": csp.csp_code or "",
        "name": csp.name or "",
        "branch_name": csp.branch_name or "",
        "rm_name": csp.rm_name or "",
    }


def _blank_value(value) -> bool:
    return not (value or "").strip() if isinstance(value, str) else value is None


def _missing_labels(csp: CSPRecord, fields) -> str:
    """The human names of this CSP's blank fields, as one readable string."""
    blank = [fo.label_of(f) for f in fields
             if hasattr(csp, f) and _blank_value(getattr(csp, f))]
    return ", ".join(blank)


async def _csps_where(session: AsyncSession, clause) -> List[CSPRecord]:
    statement = select(CSPRecord)
    if clause is not None:
        statement = statement.where(clause)
    return list((await session.execute(
        statement.order_by(CSPRecord.csp_id).limit(MAX_ROWS)
    )).scalars().all())


async def _csps_by_id(session: AsyncSession, csp_ids) -> List[CSPRecord]:
    ids = list(csp_ids)
    if not ids:
        return []
    return list((await session.execute(
        select(CSPRecord).where(CSPRecord.csp_id.in_(ids))
        .order_by(CSPRecord.csp_id).limit(MAX_ROWS)
    )).scalars().all())


# ---- record completeness ------------------------------------------------

def _completeness(fields, *, name_the_gaps=True):
    """A finder for 'these CSPs have one of these fields blank'."""
    async def finder(session):
        records = await _csps_where(session, mc._any_blank(fields))
        rows = []
        for csp in records:
            row = _csp_row(csp)
            if name_the_gaps:
                row["missing"] = _missing_labels(csp, fields)
            rows.append(row)
        columns = CSP_COLUMNS + ([MISSING_COLUMN] if name_the_gaps else [])
        return columns, rows
    return finder


_FINDERS["data.missing_csp_details"] = _completeness(fo.CSP_OWNED)
_FINDERS["data.missing_org_details"] = _completeness(fo.ORG_OWNED)


@finds("data.complete")
async def _complete(session):
    clause = mc._any_blank(tuple(fo.CSP_OWNED) + tuple(fo.ORG_OWNED))
    records = await _csps_where(session, ~clause)
    return CSP_COLUMNS, [_csp_row(c) for c in records]


@finds("data.missing_photo")
async def _missing_photo(session):
    records = await _csps_where(session, mc._blank("photo_url"))
    return CSP_COLUMNS, [_csp_row(c) for c in records]


@finds("data.awaiting_rm")
async def _awaiting_rm(session):
    from app.services.rm_resolution import UNRESOLVED

    records = await _csps_where(
        session, CSPRecord.rm_resolution == UNRESOLVED)
    return CSP_COLUMNS, [_csp_row(c) for c in records]


# ---- verification -------------------------------------------------------

@finds("verification.total")
async def _total(session):
    return CSP_COLUMNS, [_csp_row(c) for c in await _csps_where(session, None)]


@finds("verification.confirmed")
async def _confirmed(session):
    ids = (await session.execute(select(distinct(DataRequest.csp_id))
                                 .where(DataRequest.status == "answered")
                                 )).scalars().all()
    return CSP_COLUMNS, [_csp_row(c) for c in await _csps_by_id(session, ids)]


@finds("verification.waiting_on_csp")
async def _waiting(session):
    now = datetime.now(timezone.utc)
    ids = (await session.execute(
        select(distinct(DataRequest.csp_id)).where(
            DataRequest.status == "open", DataRequest.expires_at > now)
    )).scalars().all()
    return CSP_COLUMNS, [_csp_row(c) for c in await _csps_by_id(session, ids)]


@finds("verification.expired")
async def _expired(session):
    now = datetime.now(timezone.utc)
    answered = select(DataRequest.csp_id).where(
        DataRequest.status == "answered")
    ids = (await session.execute(
        select(distinct(DataRequest.csp_id)).where(
            DataRequest.expires_at <= now,
            DataRequest.status.in_(("open", "expired")),
            DataRequest.csp_id.notin_(answered),
        )
    )).scalars().all()
    return CSP_COLUMNS, [_csp_row(c) for c in await _csps_by_id(session, ids)]


@finds("verification.not_contacted")
async def _not_contacted(session):
    asked = select(DataRequest.csp_id)
    records = await _csps_where(session, CSPRecord.csp_id.notin_(asked))
    return CSP_COLUMNS, [_csp_row(c) for c in records]


ANSWER_YES, ANSWER_NO, ANSWER_NONE = "Yes", "No", "Not answered"


def _held_answer(value) -> str:
    """Three states, not two. Never asked is not the same as No."""
    text = (value or "").strip().lower()
    if text == "yes":
        return ANSWER_YES
    if text == "no":
        return ANSWER_NO
    return ANSWER_NONE


@finds("verification.documents_held")
async def _documents_held(session, field: Optional[str] = None):
    """Who said they already hold a document, and who said they do not.

    `field` names the row that was clicked. It is checked against the
    known questions rather than used to look up an attribute directly —
    an unchecked name here would let a URL read any column on the record.
    """
    if field is None:
        raise ValueError(
            "Choose a document: this number is one row per document, so "
            "there is no single list behind all of them."
        )
    if field not in fo.DOCUMENTS_HELD:
        raise KeyError(f"{field!r} is not one of the documents CSPs are "
                       f"asked about.")

    records = await _csps_where(session, None)
    order = {ANSWER_YES: 0, ANSWER_NO: 1, ANSWER_NONE: 2}
    rows = []
    for csp in records:
        row = _csp_row(csp)
        row["answer"] = _held_answer(getattr(csp, field, None))
        rows.append(row)
    rows.sort(key=lambda r: (order[r["answer"]], r["csp_code"]))
    columns = CSP_COLUMNS[:2] + [
        {"key": "answer", "label": fo.held_document_name(field)},
    ] + CSP_COLUMNS[2:]
    return columns, rows


# ---- documents ----------------------------------------------------------

@finds("documents.generated")
async def _generated(session):
    """One row per document, because that is what the number counts."""
    rows = (await session.execute(
        select(StoredDocument.csp_id, StoredDocument.document_type)
        .distinct()
        .order_by(StoredDocument.csp_id)
        .limit(MAX_ROWS)
    )).all()
    by_id = {c.csp_id: c for c in
             await _csps_by_id(session, {r[0] for r in rows})}
    out = []
    for csp_id, document_type in rows:
        csp = by_id.get(csp_id)
        row = _csp_row(csp) if csp else {"csp_id": csp_id, "csp_code": csp_id,
                                         "name": "", "branch_name": "",
                                         "rm_name": ""}
        code = registry.code_of(document_type)
        row = dict(row)
        row["document"] = registry.label(code) or code
        out.append(row)
    return CSP_COLUMNS + [{"key": "document", "label": "Document"}], out


@finds("documents.mailed")
async def _mailed(session):
    ids = await mc._csps_emailed(session, EmailStatus.SENT)
    return CSP_COLUMNS, [_csp_row(c) for c in await _csps_by_id(session, ids)]


@finds("documents.failed")
async def _failed(session):
    sent = await mc._csps_emailed(session, EmailStatus.SENT)
    failed = await mc._csps_emailed(session, EmailStatus.FAILED)
    return CSP_COLUMNS, [_csp_row(c)
                         for c in await _csps_by_id(session, failed - sent)]


@finds("documents.pending")
async def _pending(session):
    have = set((await session.execute(
        select(distinct(StoredDocument.csp_id)))).scalars().all())
    attempted = await mc._csps_emailed(session)
    return CSP_COLUMNS, [_csp_row(c)
                         for c in await _csps_by_id(session, have - attempted)]


# ---- the one entry point ------------------------------------------------

async def records_for(key: str, session: AsyncSession,
                      field: Optional[str] = None) -> dict:
    """The records behind one metric.

    `field` is for the metrics that are a table rather than a single
    number: it names the row that was clicked. Metrics that are one number
    ignore it, so a stray parameter cannot change what they return.

    Raises KeyError when the metric has no drill-down, which the router
    turns into a 404 rather than an empty list — an empty list would read
    as "nothing matched" when the truth is "this number does not open".
    """
    finder = _FINDERS.get(key)
    if finder is None:
        raise KeyError(f"The metric {key!r} does not open into a list.")

    if key in _TAKES_A_FIELD:
        columns, rows = await finder(session, field)
    else:
        columns, rows = await finder(session)
    return {
        "metric": key,
        "field": field,
        "columns": columns,
        "rows": rows,
        "count": len(rows),
        "truncated": len(rows) >= MAX_ROWS,
    }


# Metrics whose drill-down needs to know which row was clicked.
_TAKES_A_FIELD = {"verification.documents_held"}
