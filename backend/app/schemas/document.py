"""
CSP DocMaker — Document Schemas

Pydantic models for document generation request/response.
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from app.models.enums import DocumentType, ValidationStatus


class DocumentGenerateRequest(BaseModel):
    """Request to generate documents for a CSP."""
    csp_id: str = Field(..., description="CSP ID to generate documents for")
    document_types: List[DocumentType] = Field(
        ..., min_length=1,
        description="At least one document must be selected"
    )


class DocumentValidationDetail(BaseModel):
    """Validation result for a single document."""
    document_type: DocumentType
    validation_status: ValidationStatus
    issues: Optional[List[str]] = None


class DocumentGenerateResponse(BaseModel):
    """Document generation result."""
    job_id: str
    csp_id: str
    documents_requested: int
    message: str
