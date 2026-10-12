"""
CSP DocMaker — ORM Models Package

All models are imported here so Alembic autogenerate can discover them.
"""

from app.models.workspace import Workspace
from app.models.data_source import DataSource
from app.models.dashboard import Dashboard, DashboardWidget
from app.models.messaging import (
    MessageCampaign, MessageChannel, MessageTemplate,
)
from app.models.agent import AgentFinding, AgentRun, AgentState
from app.models.user import User
from app.models.authorization_record import AuthorizationRecord
from app.models.workspace_member import WorkspaceMember
from app.models.csp_record import CSPRecord
from app.models.processing_job import ProcessingJob
from app.models.document_job import DocumentJob
from app.models.email_job import EmailJob
from app.models.sms_job import SMSJob
from app.models.validation_result import ValidationResult
from app.models.audit_log import AuditLog
from app.models.sync_run import SyncRun
from app.models.stored_document import StoredDocument
from app.models.csp_photo import CSPPhoto
from app.models.rm_alert import RMAlert
from app.models.email_document import EmailDocument
from app.models.data_request import DataRequest
from app.models.document_template import DocumentTemplate

__all__ = [
    "WorkspaceMember",
    "Workspace",
    "DataSource",
    "Dashboard",
    "DashboardWidget",
    "MessageChannel",
    "MessageTemplate",
    "MessageCampaign",
    "AgentState",
    "AgentRun",
    "AgentFinding",
    "User",
    "AuthorizationRecord",
    "CSPRecord",
    "ProcessingJob",
    "DocumentJob",
    "EmailJob",
    "SMSJob",
    "ValidationResult",
    "AuditLog",
    "SyncRun",
    "StoredDocument",
    "CSPPhoto",
    "RMAlert",
    "EmailDocument",
    "DataRequest",
    "DocumentTemplate",
]
