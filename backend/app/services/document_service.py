"""
CSP DocMaker — Document Generation Service

Generates the four documents by filling the SUPPLIED DOCX templates
(see template_service). Documents are never built programmatically: the
templates are the source of truth for layout, and this module only supplies
values and file names.

Document Types:
  - CSP ID Card
  - CSP Certificate
  - Training Certificate
  - Business Continuity Plan (BCP)
"""

import logging
import os
import uuid
from datetime import date, datetime
from typing import List, Optional, Tuple, Union

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.services import template_service
from app.services.template_service import TemplateError

from app.services import document_registry as registry

logger = logging.getLogger(__name__)

settings = get_settings()

# File-name prefix for the supplied four. What a generated file is called
# now comes from configuration, so an uploaded document names its own output
# without anyone editing this.
_FILENAME_PREFIX = {
    DocumentType.CSP_ID_CARD: "CSP_ID_Card",
    DocumentType.CSP_CERTIFICATE: "CSP_Certificate",
    DocumentType.TRAINING_CERTIFICATE: "Training_Certificate",
    DocumentType.BCP: "BCP",
}


def output_prefix(doc_type) -> str:
    """What a generated file is called, before the CSP code."""
    from app.services import document_registry as registry

    if doc_type in _FILENAME_PREFIX:
        return _FILENAME_PREFIX[doc_type]
    try:
        return registry.get(doc_type).output_prefix
    except KeyError:
        return registry.code_of(doc_type)


def certificate_date(when: Optional[Union[date, datetime]] = None) -> str:
    """Date the certificate is made, in Training Certificate format: 15.08.2024."""
    return (when or datetime.now()).strftime("%d.%m.%Y")


def certificate_month_year(when: Optional[Union[date, datetime]] = None) -> str:
    """Month and year the certificate is made, in BCP format: March 2026."""
    return (when or datetime.now()).strftime("%B %Y")


def resolve_photo(csp: CSPRecord) -> str:
    """Path of the image to place in the CSP's document.

    Uses the CSP's own photo when available. While photos are still being
    extracted from the CRM, a placeholder box is used instead so the pipeline
    can be exercised end to end — that substitution is always logged, and it
    can be switched off with PHOTO_PLACEHOLDER_ALLOWED=false.
    """
    photo = (csp.photo_url or "").strip()
    if photo and os.path.isfile(photo):
        return photo

    if not settings.photo_placeholder_allowed:
        raise TemplateError(
            f"CSP {csp.csp_id} has no usable photo "
            f"({photo or 'no photo on the record'}), and placeholder photos are "
            f"disabled. The document cannot be produced."
        )

    logger.warning(
        "document_service.resolve_photo: CSP %s — using the PLACEHOLDER photo "
        "(no CRM photo yet). This document must not be treated as final.",
        csp.csp_id,
    )
    return template_service.PLACEHOLDER_PHOTO


def used_placeholder_photo(csp: CSPRecord) -> bool:
    """True when this CSP's documents would carry the placeholder photo."""
    photo = (csp.photo_url or "").strip()
    return not (photo and os.path.isfile(photo))


def _ensure_output_dir(csp_id: Optional[str] = None) -> str:
    """The directory this CSP's documents are written to, created if needed.

    Every CSP gets its own folder named after their CSP ID, so a run's output
    is grouped per person instead of hundreds of files landing side by side.
    """
    output_dir = settings.document_output_dir
    if csp_id:
        output_dir = os.path.join(output_dir, _safe_folder_name(csp_id))
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _safe_folder_name(csp_id: str) -> str:
    """A CSP ID reduced to something safe to use as a folder name.

    The ID comes from a spreadsheet cell, so it cannot be trusted to be a
    valid path — a stray slash would otherwise write outside the output
    directory.
    """
    cleaned = "".join(
        c if (c.isalnum() or c in "-_") else "_" for c in (csp_id or "").strip()
    )
    return cleaned or "unknown_csp"


def generate_document(
    csp: CSPRecord,
    doc_type: DocumentType,
    output_dir: str,
    certificate_date_value: Optional[date] = None,
) -> str:
    """Fill one supplied template for a CSP and return the saved file path."""
    from app.services import csp_mapping  # local import avoids a cycle

    values = csp_mapping.document_values(csp, certificate_date_value)
    photo_path = resolve_photo(csp) if doc_type in template_service.PHOTO_MARKERS else None
    filename = f"{output_prefix(doc_type)}_{csp.csp_id}_{uuid.uuid4().hex[:8]}.docx"
    filepath = os.path.join(output_dir, filename)
    template_service.fill_template(doc_type, values, filepath, photo_path=photo_path)
    logger.info("document_service: generated %s → %s", registry.code_of(doc_type), filepath)
    return filepath


def generate_documents(
    csp: CSPRecord,
    document_types: List[DocumentType],
    certificate_date_value: Optional[date] = None,
) -> List[Tuple[DocumentType, str]]:
    """Generate all requested documents for a CSP.

    Args:
        csp: The CSP record with all required data.
        document_types: Which documents to generate.
        certificate_date_value: Date printed on the certificates. Defaults to
            the CSP record's stored certificate_date.

    Returns:
        List of (document_type, filepath) tuples.

    Raises:
        RuntimeError: if any document could not be generated. Nothing is
            returned partially — the caller treats this as a failed job.
    """
    output_dir = _ensure_output_dir(csp.csp_id)
    results: List[Tuple[DocumentType, str]] = []

    for doc_type in document_types:
        # Configured documents, not a fixed four: an uploaded one is as
        # valid as a supplied one.
        if not registry.exists(doc_type):
            raise ValueError(
                f"Unknown document type: {doc_type}. "
                f"Configured: {', '.join(registry.codes()) or 'none'}"
            )
        try:
            results.append(
                (doc_type, generate_document(csp, doc_type, output_dir, certificate_date_value))
            )
        except Exception as e:
            logger.error(
                "document_service.generate_documents: failed to generate %s for CSP %s: %s: %s",
                registry.code_of(doc_type), csp.csp_id, type(e).__name__, e,
            )
            raise RuntimeError(
                f"Document generation failed for {registry.code_of(doc_type)} "
                f"(CSP {csp.csp_id}): {e}"
            ) from e

    logger.info(
        "document_service.generate_documents: generated %d document(s) for CSP %s",
        len(results), csp.csp_id,
    )
    return results
