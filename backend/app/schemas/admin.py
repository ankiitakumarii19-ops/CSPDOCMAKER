"""
CSP DocMaker — Admin Schemas

Pydantic models for Admin dashboard and monitoring.
"""

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class DashboardMetrics(BaseModel):
    """Summary metrics for the Admin dashboard."""
    total_csps: int = 0
    new_csps_today: int = 0
    documents_generated_today: int = 0
    emails_sent_today: int = 0
    failed_emails_today: int = 0
    document_validation_failures_today: int = 0
    email_validation_failures_today: int = 0
    sms_failures_today: int = 0
    processing_failures_today: int = 0
    pending_jobs: int = 0
    running_jobs: int = 0
    successful_workflows_today: int = 0
    failed_workflows_today: int = 0
    total_retries_today: int = 0
    last_excel_sync: Optional[datetime] = None
    last_successful_automation: Optional[datetime] = None


class DashboardResponse(BaseModel):
    """Admin dashboard response."""
    metrics: DashboardMetrics


class JobListResponse(BaseModel):
    """Paginated job list."""
    jobs: List[dict]
    total: int
    page: int
    page_size: int


class AuditLogEntry(BaseModel):
    """Single audit log entry."""
    id: str
    action: str
    user_email: Optional[str] = None
    resource_type: Optional[str] = None
    csp_id: Optional[str] = None
    result: str
    timestamp: datetime
    metadata: Optional[dict] = None


class AuditLogResponse(BaseModel):
    """Paginated audit log response."""
    entries: List[AuditLogEntry]
    total: int
    page: int
    page_size: int
