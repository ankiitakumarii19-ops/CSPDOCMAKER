"""
CSP DocMaker — Missing Data Service

Decides what a CSP record is still missing before its documents can be made.

The required fields are derived from the supplied templates (every placeholder
a template contains must have a value), so adding or removing a placeholder in
a template changes this automatically — there is no second hand-written list
to drift out of sync.
"""

import logging
from typing import Dict, List, Tuple

from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.schemas.missing_data import (
    DocumentMissingData,
    MissingDataCheckResponse,
    MissingField,
)
from app.services import csp_mapping

logger = logging.getLogger(__name__)

# Human-readable labels for document types.
DOCUMENT_LABELS: Dict[DocumentType, str] = {
    DocumentType.CSP_ID_CARD: "CSP ID Card",
    DocumentType.CSP_CERTIFICATE: "CSP Certificate",
    DocumentType.TRAINING_CERTIFICATE: "Training Certificate",
    DocumentType.BCP: "Business Continuity Plan (BCP)",
}


def document_label(doc_type) -> str:
    """What this document is called. Configured, so an admin can rename it."""
    from app.services import document_registry as registry

    if doc_type in DOCUMENT_LABELS:
        return DOCUMENT_LABELS[doc_type]
    try:
        return registry.get(doc_type).name
    except KeyError:
        return registry.code_of(doc_type)


def required_fields(doc_type: DocumentType) -> List[Tuple[str, str, str]]:
    """(canonical field, label, input type) a document needs."""
    fields = []
    for field in csp_mapping.required_fields_for(doc_type):
        label, input_type = csp_mapping.FIELD_LABELS.get(field, (field, "text"))
        fields.append((field, label, input_type))
    return fields


# Kept for callers that want the whole picture at once.
DOCUMENT_REQUIRED_FIELDS: Dict[DocumentType, List[Tuple[str, str, str]]] = {
    doc_type: required_fields(doc_type) for doc_type in DocumentType
}


def _current_value(csp: CSPRecord, field: str) -> str:
    """Value the CSP record currently holds for a canonical field."""
    if field == "certificate_date":
        # The date a certificate carries is the day it is being made, so
        # there is never nothing to print and this is never missing data.
        made_on = csp_mapping.effective_certificate_date(csp)
        return made_on.isoformat() if made_on else ""
    attr = csp_mapping.FIELD_TO_CSP_ATTR.get(field)
    if attr is None:
        return ""
    value = getattr(csp, attr, None)
    return "" if value is None else str(value).strip()


def check_missing_data(
    csp: CSPRecord,
    document_types: List[DocumentType],
) -> MissingDataCheckResponse:
    """Check which required fields are missing for the selected document types.

    Args:
        csp: The CSP record to check.
        document_types: Documents the RM wants to generate.

    Returns:
        MissingDataCheckResponse with per-document missing field details.
    """
    documents: List[DocumentMissingData] = []
    total_missing = 0

    for doc_type in document_types:
        missing_fields: List[MissingField] = []
        for field, label, input_type in required_fields(doc_type):
            if not _current_value(csp, field):
                missing_fields.append(
                    MissingField(
                        field_name=field,
                        field_label=label,
                        field_type=input_type,
                    )
                )

        documents.append(
            DocumentMissingData(
                document_type=doc_type,
                document_label=document_label(doc_type),
                missing_fields=missing_fields,
            )
        )
        total_missing += len(missing_fields)

    has_missing = total_missing > 0
    if has_missing:
        logger.info(
            "missing_data_service.check_missing_data: CSP %s has %d missing field(s) "
            "across %d document type(s)",
            csp.csp_id, total_missing, len(document_types),
        )

    return MissingDataCheckResponse(
        csp_id=csp.csp_id,
        csp_name=csp.name,
        has_missing_data=has_missing,
        documents=documents,
        total_missing_fields=total_missing,
    )


def get_all_required_fields(
    document_types: List[DocumentType],
) -> Dict[str, Tuple[str, str]]:
    """Deduplicated field_name → (label, input type) across several documents."""
    all_fields: Dict[str, Tuple[str, str]] = {}
    for doc_type in document_types:
        for field, label, input_type in required_fields(doc_type):
            all_fields.setdefault(field, (label, input_type))
    return all_fields
