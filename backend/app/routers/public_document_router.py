"""
CSP DocMaker — the private link WhatsApp fetches a CSP's documents from

No sign-in: WhatsApp's servers fetch it. What protects it is the link
itself (documents_whatsapp.link_for): signed, valid 7 days, and naming one
delivery. A wrong, altered or expired link gets the same plain 404 as a
missing one, so links cannot be probed.
"""

import logging

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.database import async_session_factory
from app.models.enums import DocumentFormat
from app.models.stored_document import StoredDocument
from app.services import documents_whatsapp
from app.workspace_context import workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public/documents", tags=["public"])

NOT_FOUND = HTTPException(status_code=404, detail="Not found.")


@router.get("/{token}")
async def documents_pdf(token: str):
    claims = documents_whatsapp.read_link(token)
    if not claims:
        raise NOT_FOUND
    try:
        with workspace(claims["ws"]):
            async with async_session_factory() as session:
                rows = (await session.execute(
                    select(StoredDocument).where(
                        StoredDocument.processing_job_id == claims["job"],
                        StoredDocument.csp_id == claims["csp"],
                        StoredDocument.file_format == DocumentFormat.PDF,
                    ).order_by(StoredDocument.document_type)
                )).scalars().all()
                pdfs = [r.file_data for r in rows]
    except Exception as e:
        logger.warning("public_document_router: %s: %s", type(e).__name__, e)
        raise NOT_FOUND
    if not pdfs:
        raise NOT_FOUND

    data = documents_whatsapp.merged_pdf(pdfs)
    name = f"CSP_Documents_{claims['csp']}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"',
                             "Cache-Control": "private, no-store"})


# ---- a CSP's photo, for the CSP sheet (No. 91) ----------------------------
# Google fetches it for the =IMAGE() formula in the sheet's Photo column,
# and the sheet script turns that into a real in-cell picture. Protected the
# same way: signed, expiring (sheet_photo.LINK_HOURS), one photo, and a link
# to a photo that has since changed answers 404.

photo_router = APIRouter(prefix="/api/public/photos", tags=["public"])


@photo_router.get("/{token}")
async def csp_photo(token: str):
    from app.models.csp_photo import CSPPhoto
    from app.services import sheet_photo

    claims = sheet_photo.read_link(token)
    if not claims:
        raise NOT_FOUND
    try:
        with workspace(claims["ws"]):
            async with async_session_factory() as session:
                photo = (await session.execute(
                    select(CSPPhoto).where(
                        CSPPhoto.csp_id == claims["csp"],
                        CSPPhoto.kind == claims["kind"],
                    )
                )).scalars().first()
    except Exception as e:
        logger.warning("public_document_router: photo: %s: %s",
                       type(e).__name__, e)
        raise NOT_FOUND
    if photo is None or not photo.checksum.startswith(claims.get("sum", "-")):
        raise NOT_FOUND
    data, media_type = _fit_for_sheet(photo.file_data, photo.content_type)
    return Response(content=data, media_type=media_type,
                    headers={"Cache-Control": "no-store"})


# Google Sheets will not take an in-cell picture much over ~2 MB or
# ~1 million pixels; a phone photo is often bigger. Shrunk copies only —
# the stored photo is never changed.
_SHEET_MAX_BYTES = 1_500_000
_SHEET_MAX_SIDE = 1000


def _fit_for_sheet(data: bytes, media_type: str):
    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            if len(data) <= _SHEET_MAX_BYTES and max(im.size) <= _SHEET_MAX_SIDE:
                return data, media_type
            im = im.convert("RGB")
            im.thumbnail((_SHEET_MAX_SIDE, _SHEET_MAX_SIDE))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=85)
            return out.getvalue(), "image/jpeg"
    except Exception as e:
        logger.warning("public_document_router: photo not resized (%s: %s)",
                       type(e).__name__, e)
        return data, media_type
