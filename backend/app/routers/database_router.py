"""
CSP DocMaker — the Database section (Super Admin)

Tracker No. 47 (plan S7) / No. 89: one place to see a CSP's complete record —
every sheet column, everything the app records about them, their photo and
every stored document. Read-only: nothing here changes data. Workspace
scoping applies as everywhere (only this workspace's CSPs are visible).
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
require_owner = require_role("super_admin")

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
    """Every CSP, searchable by code, name, district, state or RM."""
    query = select(CSPRecord)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(
            CSPRecord.csp_id.ilike(like), CSPRecord.csp_code.ilike(like),
            CSPRecord.name.ilike(like), CSPRecord.district.ilike(like),
            CSPRecord.state.ilike(like), CSPRecord.rm_name.ilike(like)))
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

    return {
        "csp_id": csp.csp_id,
        "name": csp.name,
        "level": _level(csp),
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
