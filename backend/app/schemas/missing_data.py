"""
CSP DocMaker — Missing Data Schemas

Pydantic models for missing data detection and entry.
"""

from pydantic import BaseModel, Field
from typing import List
from app.models.enums import DocumentType


class MissingField(BaseModel):
    """A single missing field."""
    field_name: str
    field_label: str
    field_type: str = Field(
        description="Input type hint: 'text', 'email', 'phone', 'address', 'date', 'photo'"
    )


class DocumentMissingData(BaseModel):
    """Missing data for a single document type."""
    document_type: DocumentType
    document_label: str
    missing_fields: List[MissingField]


class MissingDataCheckRequest(BaseModel):
    """Request to check missing data for selected documents."""
    document_types: List[DocumentType] = Field(..., min_length=1)


class MissingDataCheckResponse(BaseModel):
    """Response with missing data per document type."""
    csp_id: str
    csp_name: str
    has_missing_data: bool
    documents: List[DocumentMissingData]
    total_missing_fields: int
