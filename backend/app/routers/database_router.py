"""
CSP DocMaker — the Database section (RM, Admin and Super Admin; No. 104)

Tracker No. 47 (plan S7) / No. 89: one place to see a CSP's complete record —
every sheet column, everything the app records about them, their photo and
every stored document. Workspace scoping applies as everywhere (only this
workspace's CSPs are visible).

No. 175: a CSP can be edited from here — the whole sheet row, written to
the Google Sheet (services/csp_editor.py). RMs their own and unowned CSPs,
Admins and Super Admins any; every change logged and shown in the record.
"""

import logging
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.csp_photo import CSPPhoto, KINDS
from app.models.csp_record import CSPRecord
from app.models.enums import DocumentFormat
from app.models.stored_document import StoredDocument
from app.services import document_storage_service, ko_level
from app.services.missing_data_service import document_label

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/database", tags=["database"])
# RM, Admin and Super Admin all see every CSP's record (No. 104 — chosen
# 14 Oct 2026: all CSPs, not only an RM's own). Read-only for everyone.
require_owner = require_role("rm", "admin", "super_admin")

# The CSP data sheet's columns, in the sheet's order and with its names.
SHEET_COLUMNS = [
    ("csp_code", "CSP Code"), ("name", "CSP Name"),
    ("mobile", "CSP Mobile Number"), ("email", "CSP Email Id"),
    ("gender", "Gender"), ("branch_name", "Branch Name"),
    ("branch_code", "Branch Code"), ("branch_contact", "Branch Contact Number"),
    ("address", "Address"), ("district", "District"), ("state", "State"),
    ("ao", "AO"), ("dc", "DC"), ("dc_email", "DC Email Id"),
    ("dc_contact", "DC Contact Number"), ("lho", "LHO"),
    ("rm_name", "Relationship Manager (RM)"), ("asm_name", "ASM"),
    ("asm_email", "ASM Email Id"), ("asm_contact", "ASM Contact Number"),
    ("photo_url", "Photo"), ("rbo_name", "RBO Name"),
    ("rbo_contact", "RBO Contact No."),
]
# Internal plumbing, not part of the CSP's information.
_HIDDEN = {"id", "workspace_id"}


def _level(csp: CSPRecord) -> str:
    level = ko_level.level_of(csp.csp_code or csp.csp_id)
    return {ko_level.KO: "KO", ko_level.SUB_KO: "Sub-KO"}.get(level, "")


def _value(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "value"):
        return v.value
    return v


async def _csp_or_404(session: AsyncSession, csp_id: str) -> CSPRecord:
    csp = (await session.execute(
        select(CSPRecord).where(CSPRecord.csp_id == csp_id))).scalar_one_or_none()
    if csp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"CSP {csp_id} not found.")
    return csp


@router.get("")
async def list_csps(
    q: str = Query("", max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_owner),
):
    """Every CSP, searchable by code, name, phone, email, district, state or
    RM — matched as every search box matches (search_match, No. 175)."""
    from app.services import search_match

    query = select(CSPRecord)
    condition = search_match.csp_condition(q)
    if condition is not None:
        query = query.where(condition)
    total = (await session.execute(
        select(func.count()).select_from(query.subquery()))).scalar()
    csps = (await session.execute(
        query.order_by(CSPRecord.csp_id).limit(limit).offset(offset)
    )).scalars().all()
    ids = [c.csp_id for c in csps]

    docs, photos = defaultdict(set), defaultdict(set)
    if ids:
        for csp_id, doc_type in (await session.execute(
                select(StoredDocument.csp_id, StoredDocument.document_type)
                .where(StoredDocument.csp_id.in_(ids),
                       StoredDocument.file_format == DocumentFormat.PDF))).all():
            docs[csp_id].add(document_label(doc_type))
        for csp_id, kind in (await session.execute(
                select(CSPPhoto.csp_id, CSPPhoto.kind)
                .where(CSPPhoto.csp_id.in_(ids)))).all():
            photos[csp_id].add(kind)

    return {
        "total": total,
        "items": [{
            "csp_id": c.csp_id,
            "csp_code": c.csp_code,
            "name": c.name,
            "level": _level(c),
            "district": c.district,
            "state": c.state,
            "rm_name": c.rm_name,
            "photo": sorted(photos[c.csp_id]),
            "documents": sorted(docs[c.csp_id]),
            "updated_at": _value(c.updated_at),
        } for c in csps],
    }


@router.get("/{csp_id}")
async def get_record(
    csp_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_owner),
):
    """One CSP's complete record: sheet columns, app fields, photo, documents."""
    csp = await _csp_or_404(session, csp_id)
    sheet_keys = {k for k, _ in SHEET_COLUMNS}
    sheet = [{"key": k, "label": label, "value": _value(getattr(csp, k))}
             for k, label in SHEET_COLUMNS]
    app_fields = [
        {"key": c.name, "label": c.name.replace("_", " ").capitalize(),
         "value": _value(getattr(csp, c.name))}
        for c in CSPRecord.__table__.columns
        if c.name not in sheet_keys and c.name not in _HIDDEN
    ]

    photos = (await session.execute(
        select(CSPPhoto.kind, CSPPhoto.filename, CSPPhoto.file_size,
               CSPPhoto.updated_at)
        .where(CSPPhoto.csp_id == csp_id))).all()

    rows = (await session.execute(
        select(StoredDocument.id, StoredDocument.document_type,
               StoredDocument.version, StoredDocument.filename,
               StoredDocument.file_size, StoredDocument.created_at)
        .where(StoredDocument.csp_id == csp_id,
               StoredDocument.file_format == DocumentFormat.PDF)
        .order_by(StoredDocument.document_type, StoredDocument.version.desc())
    )).all()
    documents = defaultdict(list)
    for r in rows:
        documents[r.document_type].append({
            "id": str(r.id), "version": r.version, "filename": r.filename,
            "size": r.file_size, "created_at": _value(r.created_at)})

    from app.services import csp_access, csp_editor

    history = await session.run_sync(lambda s: csp_editor.history(s, csp_id))
    return {
        "csp_id": csp.csp_id,
        "name": csp.name,
        "level": _level(csp),
        # No. 175: whether this person may edit it, and every edit so far.
        "can_edit": csp_access.can_access(csp, user),
        "edit_history": history,
        "sheet": sheet,
        "app": app_fields,
        "photos": [{"kind": p.kind, "filename": p.filename, "size": p.file_size,
                    "updated_at": _value(p.updated_at)} for p in photos],
        "documents": [{"document_type": _value(t), "label": document_label(t),
                       "versions": v} for t, v in documents.items()],
    }


@router.get("/{csp_id}/photo/{kind}")
async def get_photo(
    csp_id: str,
    kind: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_owner),
):
    """The stored photo image (original or passport)."""
    if kind not in KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such photo kind.")
    photo = (await session.execute(
        select(CSPPhoto).where(CSPPhoto.csp_id == csp_id, CSPPhoto.kind == kind)
    )).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"No {kind} photo stored for CSP {csp_id}.")
    return Response(photo.file_data, media_type=photo.content_type,
                    headers={"Cache-Control": "private, no-store"})


@router.get("/{csp_id}/documents/{document_id}")
async def get_document(
    csp_id: str,
    document_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_owner),
):
    """One stored PDF, opened in the browser. Checked against its checksum."""
    import uuid as _uuid
    try:
        doc_uuid = _uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    doc = (await session.execute(
        select(StoredDocument).where(StoredDocument.id == doc_uuid,
                                     StoredDocument.csp_id == csp_id)
    )).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    if not document_storage_service.verify_integrity(doc):
        logger.error("database_router: stored document %s failed its checksum",
                     document_id)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This stored file failed its integrity check.")
    return Response(doc.file_data, media_type=doc.content_type, headers={
        "Content-Disposition": f'inline; filename="{doc.filename}"',
        "Cache-Control": "private, no-store"})


# ---- No. 175: edit a CSP from here -----------------------------------------

from pydantic import BaseModel, Field  # noqa: E402


class EditIn(BaseModel):
    # column title -> new value; and what the form showed for those columns
    changes: dict = Field(default_factory=dict)
    seen: dict = Field(default_factory=dict)


async def _editable(session: AsyncSession, csp_id: str, user) -> CSPRecord:
    from app.services import csp_access

    csp = await _csp_or_404(session, csp_id)
    if not csp_access.can_access(csp, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This CSP belongs to another RM. You can see it, "
                            "not change it.")
    return csp


@router.get("/{csp_id}/edit")
async def edit_form(
    csp_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_owner),
):
    """The CSP's whole sheet row, as the edit form shows it (read now)."""
    import asyncio

    from app.services import csp_editor
    from app.services.sheet_writeback_service import SheetWriteError

    csp = await _editable(session, csp_id, user)
    try:
        form = await asyncio.to_thread(csp_editor.load, csp.csp_code or csp.csp_id)
    except csp_editor.EditError as e:
        raise HTTPException(e.status_code, e.message)
    except SheetWriteError as e:
        logger.error("database_router.edit_form: %s: %s", csp_id, e)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    return {"csp_id": csp_id, "level": _level(csp), **form}


@router.put("/{csp_id}")
async def save_edit(
    csp_id: str,
    body: EditIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_owner),
):
    """Write the changed columns to the sheet and the record; log each one."""
    from app.services import csp_editor, sheet_admin_service
    from app.services.sheet_writeback_service import SheetWriteError

    csp = await _editable(session, csp_id, user)
    who = (user.get("sub") or user.get("email") or "").lower()
    code = csp.csp_code or csp.csp_id
    try:
        result = await session.run_sync(lambda s: csp_editor.save(
            s, code, {str(k): str(v) for k, v in body.changes.items()},
            {str(k): str(v) for k, v in body.seen.items()}, who))
    except csp_editor.EditError as e:
        await session.rollback()
        raise HTTPException(e.status_code, {"message": e.message,
                                            "problems": e.problems})
    except (SheetWriteError, sheet_admin_service.SheetAdminError) as e:
        await session.rollback()
        logger.error("database_router.save_edit: %s: %s", csp_id, e)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"The sheet could not be written: {e}")
    await session.commit()
    return {"saved": sorted(result["written"]), **result}
