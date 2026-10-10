"""
CSP DocMaker — the page a CSP fills in their own details on

The only endpoints in this system with no login behind them. A CSP has no
account and must never be given one; the token in their link is the whole
credential.

That shapes everything here:

  * Rate limited. A public endpoint holding a token is both a way to
    brute-force tokens and a free denial of service. Throttled per IP and
    per token.
  * Every failure answers the same way. Unknown, expired, already answered
    and cancelled are indistinguishable, so nobody can probe for live
    tokens.
  * It returns exactly one CSP's own details and nothing else. No list, no
    neighbouring record, no hierarchy — a leaked link is worth one person's
    own information and no more.
  * It writes only the fields the link was issued for. A submission naming
    anything else is refused outright rather than partly applied.

What comes back is written to the sheet as well as the database, because
the sheet is the source of truth and the sync would otherwise undo it.
"""

import logging
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.data_request import DataRequest
from app.services import field_ownership as fo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/csp-form", tags=["csp-form"])

# Deliberately identical for every failure, so the response cannot be used
# to tell a real token from a wrong one.
GONE = (
    "This link is no longer usable. It may have been used already, or it "
    "may have expired. Please contact your Relationship Manager for a new "
    "one."
)
GONE_HI = (
    "यह लिंक अब उपयोग में नहीं है। संभव है इसे पहले ही भर दिया गया हो, "
    "या इसकी समय सीमा समाप्त हो गई हो। कृपया अपने RM से संपर्क करें।"
)


# ---- rate limiting -------------------------------------------------------
#
# Small and in-process. Redis would survive a restart and span workers, and
# should be used once this runs on more than one process — but an
# unprotected public endpoint is worse than an imperfectly protected one,
# and this is honest about what it is.

WINDOW_SECONDS = 60
MAX_PER_IP = 20          # a person filling a form does not need more
MAX_PER_TOKEN = 10       # one link, opened and submitted a few times

_hits: Dict[str, List[float]] = {}


def _throttle(key: str, limit: int) -> None:
    now = time.monotonic()
    recent = [t for t in _hits.get(key, []) if now - t < WINDOW_SECONDS]
    if len(recent) >= limit:
        _hits[key] = recent
        logger.warning("csp_form_router: rate limit hit for %s", key)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Please wait a minute and try again.",
        )
    recent.append(now)
    _hits[key] = recent

    # Keep the table from growing without bound on a long-running process.
    if len(_hits) > 10_000:
        for stale in [k for k, v in _hits.items()
                      if not v or now - v[-1] > WINDOW_SECONDS]:
            _hits.pop(stale, None)


def _guard(request: Request, token: str) -> None:
    client = request.client.host if request.client else "unknown"
    _throttle(f"ip:{client}", MAX_PER_IP)
    _throttle(f"token:{token[:16]}", MAX_PER_TOKEN)


# ---- what the page sends back -------------------------------------------

class Submission(BaseModel):
    values: Dict[str, str] = Field(default_factory=dict)


def _gone() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND,
                         {"message": GONE, "message_hi": GONE_HI})


async def _resolve(session: AsyncSession, token: str) -> DataRequest:
    """The open request this token stands for, or the same refusal as always."""
    from sqlalchemy import select

    from app.services import data_request_service as drs

    request_row = (await session.execute(
        select(DataRequest).where(DataRequest.token_hash == drs._hash(token))
    )).scalars().first()

    if request_row is None or request_row.status != "open":
        raise _gone()
    if drs._is_expired(request_row):
        request_row.status = "expired"
        await session.commit()
        raise _gone()
    return request_row


async def _csp(session: AsyncSession, csp_id: str):
    from sqlalchemy import select

    from app.models.csp_record import CSPRecord

    record = (await session.execute(
        select(CSPRecord).where(CSPRecord.csp_id == csp_id)
    )).scalars().first()
    if record is None:
        raise _gone()
    return record


def _field_payload(record, field: str) -> dict:
    value = getattr(record, field, None)
    return {
        "name": field,
        "label": fo.LABELS.get(field, field),
        "label_hi": fo.LABELS_HI.get(field, ""),
        "type": fo.input_type_of(field),
        "value": "" if value is None else str(value).strip(),
    }


# ---- endpoints -----------------------------------------------------------

@router.get("/{token}")
async def open_form(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """What this CSP is being asked to check.

    Everything is returned pre-filled so the CSP confirms rather than
    retypes, and corrects what is wrong.
    """
    _guard(request, token)

    from app.workspace_context import all_workspaces, workspace

    # The token identifies the workspace; nobody has signed in to say which.
    with all_workspaces():
        request_row = await _resolve(session, token)

    with workspace(request_row.workspace_id):
        record = await _csp(session, request_row.csp_id)

        fields = [_field_payload(record, f)
                  for f in (request_row.fields or [])
                  if f not in fo.DOCUMENTS_HELD]
        documents = [
            {
                "name": f,
                "label": fo.LABELS.get(f, f),
                "label_hi": fo.LABELS_HI.get(f, ""),
                "upload_label": fo.UPLOAD_LABELS.get(f, ("", ""))[0],
                "upload_label_hi": fo.UPLOAD_LABELS.get(f, ("", ""))[1],
                "value": getattr(record, f, None) or "",
            }
            for f in (request_row.fields or []) if f in fo.DOCUMENTS_HELD
        ]

    return {
        # Shown so the person knows the form is for them. Their own name and
        # code, nothing about anybody else.
        "csp_code": record.csp_id,
        "csp_name": record.name or "",
        "fields": fields,
        "documents": documents,
        "gender_choices": [{"value": v, "label": l}
                           for v, l in fo.GENDER_CHOICES],
        "yesno_choices": [{"value": v, "label": l}
                          for v, l in fo.YESNO_CHOICES],
        "expires_at": request_row.expires_at.isoformat(),
        "submit_once": True,
    }


@router.post("/{token}")
async def submit_form(
    token: str,
    body: Submission,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Record what the CSP confirmed, and write it to the sheet."""
    _guard(request, token)

    from app.services import data_request_service as drs
    from app.services import sheet_writeback_service as wb
    from app.workspace_context import all_workspaces, workspace

    with all_workspaces():
        request_row = await _resolve(session, token)

    with workspace(request_row.workspace_id):
        record = await _csp(session, request_row.csp_id)

        allowed = set(request_row.fields or [])
        offered = {k: (v or "").strip() for k, v in (body.values or {}).items()}
        unexpected = sorted(set(offered) - allowed)
        if unexpected:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"This form does not include {', '.join(unexpected)}.",
            )

        # A blank box means "nothing to add", never "delete what you have".
        accepted = {k: v for k, v in offered.items() if v}

        for field, value in accepted.items():
            setattr(record, field, value)

        request_row.answered_values = accepted
        request_row.status = "answered"
        from datetime import datetime, timezone
        request_row.answered_at = datetime.now(timezone.utc)
        await session.commit()

        # The sheet is the source of truth; the sync would otherwise put
        # the old values straight back.
        written, skipped = {}, []
        sheet_error = None
        try:
            written, skipped = wb.write_values(record.csp_id, accepted)
        except wb.SheetWriteError as e:
            # The CSP has done their part. Their answers are saved; the
            # sheet is reconciled by an admin rather than the person being
            # told to do it again.
            sheet_error = str(e)
            logger.error(
                "csp_form_router.submit_form: CSP %s submitted but the sheet "
                "could not be updated: %s", record.csp_id, e,
            )

    logger.info(
        "csp_form_router.submit_form: CSP %s returned %d field(s)%s",
        request_row.csp_id, len(accepted),
        f", {len(skipped)} with no sheet column" if skipped else "",
    )
    return {
        "received": sorted(accepted),
        "saved_to_sheet": sorted(written),
        "message": "Thank you. Your details have been received.",
        "message_hi": (
            "धन्यवाद। आपकी जानकारी प्राप्त हो गई है।"
        ),
        # Never surfaced to the CSP as a failure — it is not their problem.
        "sheet_pending": bool(sheet_error),
    }
