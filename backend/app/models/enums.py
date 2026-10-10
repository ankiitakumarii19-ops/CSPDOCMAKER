"""
CSP DocMaker — Enums

Shared enumerations used across models and business logic.
"""

import enum


class UserRole(str, enum.Enum):
    """Who someone is, and therefore what they may do.

    SUPER_ADMIN owns the configuration: data sources, fields, document
    templates and who may sign in. ADMIN is operational — dashboards and
    monitoring only, and deliberately cannot change any of the above. RM
    works their own assigned CSPs.
    """
    RM = "rm"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class AccountStatus(str, enum.Enum):
    """User account status."""
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class AuthorizationStatus(str, enum.Enum):
    """Authorization record status from Google Sheet."""
    ACTIVE = "active"
    INACTIVE = "inactive"


class WorkflowType(str, enum.Enum):
    """Processing workflow type."""
    NEW_CSP = "new_csp"
    EXISTING_CSP = "existing_csp"


class JobState(str, enum.Enum):
    """
    Processing job states — complete state machine per Section 29.
    Each state represents a specific point in the workflow pipeline.
    """
    # Success path
    DETECTED = "detected"
    DATA_VALIDATING = "data_validating"
    DATA_VALIDATED = "data_validated"
    DOCUMENT_GENERATING = "document_generating"
    DOCUMENT_GENERATED = "document_generated"
    DOCUMENT_VALIDATING = "document_validating"
    DOCUMENT_VALIDATED = "document_validated"
    EMAIL_VALIDATING = "email_validating"
    EMAIL_VALIDATED = "email_validated"
    READY_TO_SEND = "ready_to_send"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    # An RM's request whose CSP is still missing details. Kept, not failed:
    # it is finished automatically once the sheet has the data.
    PENDING_DATA = "pending_data"
    EMAIL_SENDING = "email_sending"
    EMAIL_SENT = "email_sent"
    SMS_SENDING = "sms_sending"
    SMS_SENT = "sms_sent"
    COMPLETED = "completed"

    # Failure states
    FAILED_DATA_VALIDATION = "failed_data_validation"
    FAILED_DOCUMENT_GENERATION = "failed_document_generation"
    FAILED_DOCUMENT_VALIDATION = "failed_document_validation"
    FAILED_PDF_CONVERSION = "failed_pdf_conversion"
    FAILED_EMAIL_VALIDATION = "failed_email_validation"
    FAILED_EMAIL_SENDING = "failed_email_sending"
    FAILED_SMS_SENDING = "failed_sms_sending"


class DocumentType(str, enum.Enum):
    """Document types available for generation."""
    CSP_ID_CARD = "csp_id_card"
    CSP_CERTIFICATE = "csp_certificate"
    TRAINING_CERTIFICATE = "training_certificate"
    BCP = "bcp"


class DocumentFormat(str, enum.Enum):
    """Stored file formats. DOCX is what generation produces; PDF is the
    converted copy that is emailed to the CSP."""
    DOCX = "docx"
    PDF = "pdf"


class ValidationStatus(str, enum.Enum):
    """Validation outcome."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class ValidationType(str, enum.Enum):
    """Type of validation performed."""
    DETERMINISTIC = "deterministic"
    AI_ASSISTED = "ai_assisted"
    EMAIL_VALIDATION = "email_validation"
    DATA_VALIDATION = "data_validation"


class EmailStatus(str, enum.Enum):
    """Email delivery status."""
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


class SMSStatus(str, enum.Enum):
    """SMS delivery status."""
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


# OTPMethod was removed with SMS delivery: an OTP is always emailed, so
# there is no method to choose.
