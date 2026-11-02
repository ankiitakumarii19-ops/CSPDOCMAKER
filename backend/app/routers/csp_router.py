"""
CSP DocMaker — CSP Router

API endpoints for CSP search and retrieval.
Currently a stub — will be fully implemented when CSP data source is configured.

  GET /api/csps/search?q=<query>  — Search CSPs by ID or name
  GET /api/csps/{csp_id}          — Get CSP details by ID
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_any_role, require_role
from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.schemas.csp import (
    CSPDetailResponse, CSPSearchResponse, CSPUpdateRequest,
)
from app.services import csp_access

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/search", response_model=CSPSearchResponse)
async def search_csps(
    q: str = Query(..., min_length=1, description="Part of a CSP code, name, phone, email, district, state or RM"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_any_role),
):
    """Search CSP records (No. 175: services/search_match — part of a word,
    any capitals and spaces, phone by its digits).

    Every role finds every CSP (owner's choice, 2 Nov 2026); `can_act` says
    whether this person may act on each one — an RM only on their own and
    unowned CSPs, the rest is read-only for them.
    """
    from app.services import search_match

    try:
        condition = search_match.csp_condition(q)
        if condition is None:
            return CSPSearchResponse(results=[], total=0, query=q)
        records = (await db.execute(
            select(CSPRecord).where(condition)
            .order_by(*search_match.best_first(q)).limit(limit)
        )).scalars().all()

        results = []
        for r in records:
            item = CSPDetailResponse.model_validate(r)
            item.can_act = csp_access.can_access(r, current_user)
            results.append(item)
        return CSPSearchResponse(results=results, total=len(results), query=q)
    except Exception as e:
        logger.error(
            "csp_router.search_csps: search failed for query '%s': %s: %s",
            q, type(e).__name__, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CSP search failed due to a server error.",
        )


@router.get("/{csp_id}/photo")
async def get_csp_photo(
    csp_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_any_role),
):
    """The CSP's photo as every screen shows it (No. 102): the edited
    passport version, or the photo as obtained while that is not made yet.
    404 when there is none.

    Every signed-in RM, Admin and Super Admin may see any CSP's photo: the
    Database and Sheets screens show every CSP to all three (decided 14 Oct
    2026, No. 104), so limiting the photo to an RM's own CSPs only left
    empty boxes beside records they can already read."""
    from fastapi import Response

    from app.models.csp_photo import ORIGINAL, PASSPORT, CSPPhoto

    query = select(CSPRecord.csp_id).where(CSPRecord.csp_id == csp_id)
    if (await db.execute(query)).scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"CSP with ID '{csp_id}' not found.")

    rows = {p.kind: p for p in (await db.execute(
        select(CSPPhoto).where(CSPPhoto.csp_id == csp_id))).scalars().all()}
    photo = rows.get(PASSPORT) or rows.get(ORIGINAL)
    if photo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No photo for CSP {csp_id} yet.")
    return Response(photo.file_data, media_type=photo.content_type,
                    headers={"Cache-Control": "private, no-store",
                             "X-Photo-Kind": photo.kind})


@router.get("/{csp_id}", response_model=CSPDetailResponse)
async def get_csp(
    csp_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_any_role),
):
    """Get a CSP record by its ID."""
    try:
        query = select(CSPRecord).where(CSPRecord.csp_id == csp_id)
        scope = csp_access.accessible_filter(current_user)
        if scope is not None:
            # A CSP this RM may not access is reported exactly like a missing
            # one, so IDs cannot be probed.
            query = query.where(scope)
        result = await db.execute(query)
        record = result.scalar_one_or_none()
    except Exception as e:
        logger.error(
            "csp_router.get_csp: DB query failed for csp_id=%s: %s: %s",
            csp_id, type(e).__name__, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve CSP data.",
        )

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CSP with ID '{csp_id}' not found.",
        )

    return CSPDetailResponse.model_validate(record)


@router.patch("/{csp_id}", response_model=CSPDetailResponse)
async def update_csp(
    csp_id: str,
    updates: CSPUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("rm")),
):
    """Fill in a CSP's missing data before generating documents.

    The body is validated against CSPUpdateRequest, so an unknown or retired
    field is rejected with 422 rather than accepted and dropped. Types are
    enforced there too: certificate_date is a real date, not a string.

    Note on sheet-owned fields: the CSP sheet is the source of truth and is
    synced every minute, so a correction to a sheet column (address, branch,
    ASM, ...) is overwritten on the next sync until write-back to the sheet is
    built. certificate_date is owned by the application and does survive.

    The photo is updated separately, via the document router's upload-photo
    endpoint.
    """
    query = select(CSPRecord).where(CSPRecord.csp_id == csp_id)
    scope = csp_access.accessible_filter(current_user)
    if scope is not None:
        query = query.where(scope)
    result = await db.execute(query)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CSP with ID '{csp_id}' not found.",
        )

    # exclude_unset keeps "field not sent" distinct from "field sent as null",
    # so an untouched field is never blanked out.
    supplied = updates.model_dump(exclude_unset=True, exclude_none=True)
    if not supplied:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No values provided for update.",
        )

    changed = []
    for field, value in supplied.items():
        # Strings are trimmed; a date stays a date.
        cleaned = value.strip() if isinstance(value, str) else value
        if isinstance(cleaned, str) and not cleaned:
            continue  # an empty box is "not supplied", not "erase this"
        if getattr(record, field) != cleaned:
            setattr(record, field, cleaned)
            changed.append(field)

    if changed:
        db.add(record)
        await db.commit()
        await db.refresh(record)

    logger.info(
        "csp_router.update_csp: CSP %s — %d field(s) changed by %s: %s",
        csp_id, len(changed), current_user.get("sub"), ", ".join(changed) or "none",
    )

    return CSPDetailResponse.model_validate(record)



class AutoIssueRequest(BaseModel):
    """Put an existing CSP into the automatic pipeline.

    certificate_date is accepted only so older callers do not break. It is
    NOT used: since 11 Oct 2026 (tracker No. 56) a certificate always
    carries the day it is made.
    """

    certificate_date: Optional[date] = None


@router.post("/{csp_id}/auto-issue")
async def auto_issue(
    csp_id: str,
    body: AutoIssueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("rm")),
):
    """Hand this CSP to the automation and let it finish on its own.

    After this, the CSP is treated exactly like a newly detected one: the
    worker generates, validates, converts, stores and emails without the RM
    doing another thing. If something is missing it raises the same alert
    and keeps retrying until the gap is filled.

    Enrolling is deliberate and one CSP at a time. Baseline CSPs stay out of
    the automation by default precisely so a first sync cannot email an
    entire organisation.
    """
    # Scoped the same way every other read is: a CSP this RM may not reach
    # is reported exactly like a missing one, so IDs cannot be probed.
    query = select(CSPRecord).where(CSPRecord.csp_id == csp_id)
    scope = csp_access.accessible_filter(current_user)
    if scope is not None:
        query = query.where(scope)
    record = (await db.execute(query)).scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CSP {csp_id} not found.",
        )
    if record.send_hold:
        # Inactive / not live yet (No. 121): nothing is made or sent.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Nothing can be sent to {record.name} ({csp_id}): "
                   f"{record.send_hold}")

    if record.new_csp_processed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{csp_id} has already been issued. Generate from the "
                f"workflow screen if you need a fresh copy."
            ),
        )

    if body.certificate_date is not None:
        record.certificate_date = body.certificate_date

    # Said plainly rather than discovered three minutes later.
    from app.services.missing_data_service import check_missing_data

    missing = check_missing_data(record, list(DocumentType))

    already = record.auto_enrolled_at is not None
    if not already:
        record.auto_enrolled_at = datetime.now(timezone.utc)
        record.auto_enrolled_by = (
            current_user.get("email") or current_user.get("sub"))
    await db.commit()

    logger.info(
        "csp_router.auto_issue: %s enrolled by %s (missing=%d)",
        csp_id, record.auto_enrolled_by, missing.total_missing_fields,
    )

    return {
        "csp_id": csp_id,
        "enrolled": True,
        "already_enrolled": already,
        "has_missing_data": missing.has_missing_data,
        "missing_fields": sorted({
            f.field_label
            for doc in missing.documents for f in doc.missing_fields
        }),
        "message": (
            "Nothing more to do — the documents will be generated and "
            "emailed within a few minutes."
            if not missing.has_missing_data else
            "Enrolled. It will complete on its own as soon as the missing "
            "details arrive; until then you will see an alert."
        ),
    }


# ---- No. 174: message a CSP, open their chat -------------------------------
# RMs for their own (and unowned) CSPs — the owner's choice, 2 Nov 2026 —
# Admins and Super Admins for every CSP.

class CspMessageIn(BaseModel):
    kind: str = "custom"            # custom | details_form
    channel: str = "whatsapp"       # whatsapp | email
    text: str = ""


async def _my_csp(session: AsyncSession, csp_id: str, user: dict) -> CSPRecord:
    record = (await session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == csp_id))).scalars().first()
    if record is None or not csp_access.can_access(record, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such CSP.")
    return record


@router.get("/{csp_id}/conversation", summary="This CSP's WhatsApp chat")
async def csp_conversation(
    csp_id: str,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_any_role),
):
    from app.routers.whatsapp_message_router import chat_for_csp

    await _my_csp(session, csp_id, user)
    return await chat_for_csp(session, csp_id)


@router.post("/{csp_id}/message", summary="Send this CSP a message now")
async def message_csp(
    csp_id: str,
    body: CspMessageIn,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_any_role),
):
    """A message a person sends (services/manual_messages.py): refused for a
    CSP on hold, and the details form never goes to an existing CSP."""
    from app.services import manual_messages as mm

    if body.kind not in (mm.CUSTOM, mm.DETAILS_FORM):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown message kind.")
    if len(body.text) > 2000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The message is too long.")
    await _my_csp(session, csp_id, user)
    who = (user.get("sub") or user.get("email") or "").lower()

    def _send(sync):
        record = sync.execute(select(CSPRecord).where(
            CSPRecord.csp_id == csp_id)).scalars().first()
        return mm.send(sync, record, kind=body.kind, channel=body.channel,
                       text=body.text, by=who)

    result = await session.run_sync(_send)
    await session.commit()
    return result

