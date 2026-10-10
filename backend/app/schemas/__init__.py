"""
CSP DocMaker — Pydantic Schemas Package

Request/response schemas for API validation.
"""

from app.schemas.auth import (
    SignupRequest,
    SignupResponse,
    LoginRequest,
    LoginResponse,
    OTPVerifyRequest,
    OTPVerifyResponse,
    OTPSendRequest,
)
from app.schemas.csp import (
    CSPSearchResponse,
    CSPDetailResponse,
)
from app.schemas.document import (
    DocumentGenerateRequest,
    DocumentGenerateResponse,
)
from app.schemas.workflow import (
    WorkflowProcessRequest,
    WorkflowStatusResponse,
)
from app.schemas.admin import (
    DashboardResponse,
    JobListResponse,
    AuditLogResponse,
)

__all__ = [
    "SignupRequest", "SignupResponse",
    "LoginRequest", "LoginResponse",
    "OTPVerifyRequest", "OTPVerifyResponse", "OTPSendRequest",
    "CSPSearchResponse", "CSPDetailResponse",
    "DocumentGenerateRequest", "DocumentGenerateResponse",
    "WorkflowProcessRequest", "WorkflowStatusResponse",
    "DashboardResponse", "JobListResponse", "AuditLogResponse",
]
