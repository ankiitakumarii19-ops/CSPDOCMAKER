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
