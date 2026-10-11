"""
CSP DocMaker — Document Router

Endpoints for missing data check, document generation, and validation.
"""

import os
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_session
from app.dependencies import require_role
from app.models.csp_record import CSPRecord
from app.schemas.missing_data import MissingDataCheckRequest, MissingDataCheckResponse
from app.services import csp_access
from app.services.missing_data_service import check_missing_data, DOCUMENT_LABELS
from app.services import document_service
from app.services import document_validation_service
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

settings = get_settings()


async def _get_accessible_csp(session: AsyncSession, csp_id: str, user: dict) -> CSPRecord:
    """Load a CSP the caller may act on, or 404.

    A CSP that exists but belongs to another RM is reported exactly like a
    missing one, so CSP IDs cannot be probed.
    """
    query = select(CSPRecord).where(CSPRecord.csp_id == csp_id)
    scope = csp_access.accessible_filter(user)
    if scope is not None:
        query = query.where(scope)
    csp = (await session.execute(query)).scalar_one_or_none()
    if not csp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CSP with ID '{csp_id}' not found.",
        )
    return csp


@router.post(
    "/check-missing/{csp_id}",
    response_model=MissingDataCheckResponse,
    summary="Check missing data for document generation",
)
async def check_missing_data_endpoint(
    csp_id: str,
    request: MissingDataCheckRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("rm")),
):
    """Check which required fields are missing for the selected document types.

    This must be called BEFORE document generation to ensure all required
    data is available.
    """
    csp = await _get_accessible_csp(session, csp_id, user)

    return check_missing_data(csp, request.document_types)


@router.post(
    "/generate/{csp_id}",
    summary="Generate documents for a CSP",
)
async def generate_documents_endpoint(
    csp_id: str,
    request: MissingDataCheckRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("rm")),
):
    """Generate the requested documents for a CSP.

    Performs missing data check first — if any required fields are missing,
    returns a 422 error with the missing data details.

    After generation, validates all documents against source data.
    """
    csp = await _get_accessible_csp(session, csp_id, user)

    # Gate: check missing data first
    missing_check = check_missing_data(csp, request.document_types)
    if missing_check.has_missing_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": (
                    f"Cannot generate documents: {missing_check.total_missing_fields} "
                    f"required field(s) are missing."
                ),
                "missing_data": missing_check.model_dump(),
            },
        )

    # Generate documents
    try:
        generated = document_service.generate_documents(csp, request.document_types)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document generation failed: {str(e)}",
        )

    # Validate documents against source data
    all_passed, validation_results = document_validation_service.validate_all_documents(
        csp, generated,
    )

    # Validate CSP email
    email_valid, email_error = document_validation_service.validate_csp_email(csp)

    return {
        "csp_id": csp_id,
        "csp_name": csp.name,
        "documents_generated": len(generated),
        "document_types": [dt.value for dt, _ in generated],
        "document_labels": [DOCUMENT_LABELS.get(dt, dt.value) for dt, _ in generated],
        "filepaths": [fp for _, fp in generated],
        "validation": {
            "all_passed": all_passed,
            "results": validation_results,
        },
        "email_validation": {
            "valid": email_valid,
            "error": email_error,
            "recipient": csp.email,
        },
        "ready_to_send": all_passed and email_valid,
    }


@router.post(
    "/upload-photo/{csp_id}",
    summary="Upload CSP photo for ID Card",
)
async def upload_photo(
    csp_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("rm")),
):
    """Upload a photo for a CSP — required for the CSP ID Card document."""
    csp = await _get_accessible_csp(session, csp_id, user)

    # Validate file type
    allowed_types = {"image/jpeg", "image/png", "image/jpg", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Invalid file type: '{file.content_type}'. "
                f"Allowed types: JPEG, PNG, WebP."
            ),
        )

    # Save photo
    photos_dir = os.path.join(settings.document_output_dir, "photos")
    os.makedirs(photos_dir, exist_ok=True)

    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "jpg"
    photo_filename = f"{csp_id}_{uuid.uuid4().hex[:8]}.{ext}"
    photo_path = os.path.join(photos_dir, photo_filename)

    contents = await file.read()
    with open(photo_path, "wb") as f:
        f.write(contents)

    # Update CSP record
    csp.photo_url = photo_path
    session.add(csp)
    await session.commit()

    logger.info(
        "document_router.upload_photo: saved photo for CSP %s → %s",
        csp_id, photo_path,
    )

    return {
        "csp_id": csp_id,
        "photo_url": photo_path,
        "message": f"Photo uploaded successfully for CSP {csp_id}.",
    }
