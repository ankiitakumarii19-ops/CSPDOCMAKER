"""
CSP DocMaker — Workflow Schemas

Pydantic models for workflow processing.
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from app.models.enums import DocumentType, JobState, WorkflowType


class WorkflowProcessRequest(BaseModel):
    """Request to initiate a complete document-email workflow."""
    csp_id: str
    document_types: List[DocumentType] = Field(..., min_length=1)


class WorkflowStatusResponse(BaseModel):
    """Workflow job status."""
    job_id: str
    csp_id: str
    workflow_type: WorkflowType
    current_state: JobState
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
