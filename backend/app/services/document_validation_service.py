"""
CSP DocMaker — Document Validation Service

Validates generated DOCX documents against the CSP source data.
Opens each generated document, extracts key text content, and compares
it to the trusted CSP record. If any field does not match, validation fails.

CRITICAL: Documents must NOT be sent to CSPs if validation fails.
"""

import logging
import os
from typing import List, Dict, Optional, Tuple

from docx import Document

from app.models.csp_record import CSPRecord
from app.services import csp_mapping, template_service
from app.models.enums import DocumentType, ValidationStatus

from app.services import document_registry as registry
from app import telemetry

logger = logging.getLogger(__name__)


# Validation is derived from the supplied templates: every placeholder a
# template contains must appear in the generated document with exactly the
# value this run supplied. There is no second hand-written list to drift.
def _extract_document_text(filepath: str) -> str:
    """Extract all text from a DOCX: body, tables, text boxes, headers, footers.

    The ID Card and Training Certificate keep their content in text boxes, so
    a body-and-tables-only walk reads them as empty.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Document file not found: {filepath}")

    doc = Document(filepath)
    return "\n".join(
        "".join(run.text for run in para.runs)
        for para in template_service._all_paragraphs(doc)
    )


@telemetry.traced("validate_document", "document_validation_service")
def validate_document(
    csp: CSPRecord,
    doc_type: DocumentType,
    filepath: str,
    certificate_date_value=None,
) -> Tuple[ValidationStatus, List[Dict[str, str]]]:
    """Validate a single generated document against the CSP source data.

    Args:
        csp: The trusted CSP record.
        doc_type: The type of document generated.
        filepath: Path to the generated DOCX file.
        certificate_date_value: The date the document was generated with, when
            it was not taken from the CSP record. Validation must compare the
            document against the values that produced it.

    Returns:
        Tuple of (status, issues).
        status: ValidationStatus.PASSED or FAILED.
        issues: List of dicts with 'field', 'expected', 'found' for mismatches.
    """
    issues: List[Dict[str, str]] = []

    try:
        doc_text = _extract_document_text(filepath)
    except FileNotFoundError as e:
        logger.error(
            "document_validation_service.validate_document: file not found: %s",
            filepath,
        )
        return ValidationStatus.ERROR, [
            {"field": "file", "expected": filepath, "found": "FILE_NOT_FOUND"}
        ]
    except Exception as e:
        logger.error(
            "document_validation_service.validate_document: failed to read %s: %s: %s",
            filepath, type(e).__name__, e,
        )
        return ValidationStatus.ERROR, [
            {"field": "file", "expected": filepath, "found": f"READ_ERROR: {e}"}
        ]

    # Through the same transformation the filler uses, or validation
    # looks for text the document was never going to contain.
    values = template_service.values_for(
        doc_type, csp_mapping.document_values(csp, certificate_date_value))
    for placeholder, field in template_service.PLACEHOLDER_FIELDS[doc_type].items():
        expected_value = str(values.get(field, "")).strip()
        if not expected_value:
            issues.append({
                "field": placeholder,
                "expected": "(no value)",
                "found": "MISSING_SOURCE_VALUE",
            })
            continue
        if expected_value not in doc_text:
            issues.append({
                "field": placeholder,
                "expected": expected_value,
                "found": "NOT_FOUND_IN_DOCUMENT",
            })
            logger.warning(
                "document_validation_service.validate_document: "
                "CSP %s %s — field '%s' expected '%s' not found in document",
                csp.csp_id, registry.code_of(doc_type), placeholder, expected_value,
            )

    # A document whose template carries a photo must actually contain it.
    if doc_type in template_service.PHOTO_MARKERS:
        if template_service.has_photo_marker(filepath, doc_type):
            issues.append({
                "field": "Photo",
                "expected": "photo image",
                "found": "PHOTO_MARKER_STILL_PRESENT",
            })
        elif template_service.count_images(filepath) <= template_service.count_images(
            template_service.template_path(doc_type)
        ):
            issues.append({
                "field": "Photo",
                "expected": "photo image",
                "found": "NO_IMAGE_ADDED",
            })

    # KO or Sub-KO, by the length of the code (No. 57). Checked only where
    # the template asks for it and the level is known.
    from app.services import ko_level
    level_label = ko_level.label_for(getattr(csp, "csp_code", None))
    if level_label and ko_level.TOKEN in _extract_document_text(
            str(template_service.template_path(doc_type))):
        wrong = (ko_level.TOKEN in doc_text
                 or f"{level_label} Code" not in doc_text
                 # "Sub-KO Code" contains "KO Code", so a KO's certificate is
                 # also checked for not saying Sub-KO.
                 or (level_label == "KO" and "Sub-KO Code" in doc_text))
        if wrong:
            issues.append({
                "field": "KO / Sub-KO",
                "expected": f"{level_label} Code",
                "found": "WRONG_KO_WORDING",
            })

    # The template must not still contain any placeholder token.
    leftover = template_service.find_leftover_placeholders_in_file(filepath, doc_type)
    for name in sorted(leftover):
        issues.append({
            "field": name,
            "expected": "(placeholder replaced)",
            "found": "PLACEHOLDER_STILL_PRESENT",
        })

    if issues:
        logger.error(
            "document_validation_service.validate_document: "
            "VALIDATION FAILED for CSP %s %s — %d issue(s) found",
            csp.csp_id, registry.code_of(doc_type), len(issues),
        )
        return ValidationStatus.FAILED, issues
    else:
        logger.info(
            "document_validation_service.validate_document: "
            "PASSED for CSP %s %s",
            csp.csp_id, registry.code_of(doc_type),
        )
        return ValidationStatus.PASSED, []


def validate_all_documents(
    csp: CSPRecord,
    generated_docs: List[Tuple[DocumentType, str]],
    certificate_date_value=None,
) -> Tuple[bool, List[Dict]]:
    """Validate all generated documents for a CSP.

    Args:
        csp: The trusted CSP record.
        generated_docs: List of (doc_type, filepath) from generation.

    Returns:
        Tuple of (all_passed, results).
        all_passed: True if ALL documents passed validation.
        results: List of validation results per document.
    """
    all_passed = True
    results = []

    for doc_type, filepath in generated_docs:
        status, issues = validate_document(
            csp, doc_type, filepath, certificate_date_value)

        results.append({
            "document_type": registry.code_of(doc_type),
            "validation_status": status.value,
            "issues": issues,
            "filepath": filepath,
        })

        if status != ValidationStatus.PASSED:
            all_passed = False

    if all_passed:
        logger.info(
            "document_validation_service.validate_all_documents: "
            "ALL %d document(s) PASSED for CSP %s",
            len(generated_docs), csp.csp_id,
        )
    else:
        logger.error(
            "document_validation_service.validate_all_documents: "
            "VALIDATION FAILED for CSP %s — documents MUST NOT be sent",
            csp.csp_id,
        )

    return all_passed, results


def validate_csp_email(csp: CSPRecord) -> Tuple[bool, str]:
    """Validate the CSP's registered email address.

    Args:
        csp: The CSP record.

    Returns:
        Tuple of (valid, error_message).
    """
    email = csp.email
    if not email or not email.strip():
        return False, f"CSP {csp.csp_id} has no registered email address."

    email = email.strip()

    # Basic email validation
    if "@" not in email or "." not in email.split("@")[-1]:
        return False, (
            f"CSP {csp.csp_id} has an invalid email address: '{email}'. "
            f"Email must contain '@' and a valid domain."
        )

    # Check for common issues
    if email.startswith("@") or email.endswith("@"):
        return False, (
            f"CSP {csp.csp_id} has a malformed email address: '{email}'."
        )

    local_part, domain = email.rsplit("@", 1)
    if not local_part or not domain or "." not in domain:
        return False, (
            f"CSP {csp.csp_id} email '{email}' has an invalid domain."
        )

    logger.info(
        "document_validation_service.validate_csp_email: "
        "email validation PASSED for CSP %s (%s)",
        csp.csp_id, email,
    )
    return True, ""
