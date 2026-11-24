"""
CSP DocMaker — the weekly health email (PROJECT-REGISTER No. 214, Stage 7:
TK-060, ZU-06)

Once a week, on the workspace's day and hour (Settings → Look and weekly
email), to its Super Admins (or the addresses set):

  * the week's numbers: WhatsApps sent / failed / waiting, emails sent /
    failed, documents made, new records, form links sent and answered;
  * what is stuck: form links open, WhatsApps waiting for approval;
  * WHAT TO FIX IN THE SETUP (ZU-06): fixed checks, each with where to fix
    it — e.g. "messages are on but WhatsApp is not connected".

Fixed rules over the workspace's own records; no AI. Sent at most once a
week (the audit log remembers), only from the server (never a laptop or the
test copy), and never while emails are paused.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select

logger = logging.getLogger(__name__)
ACTION = "weekly_health_email"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def numbers(session, since: datetime) -> Dict[str, int]:
    from app.models.csp_record import CSPRecord
    from app.models.data_request import DataRequest
    from app.models.email_message import EmailMessage
    from app.models.stored_document import StoredDocument
    from app.models.whatsapp_message import WhatsAppMessage

    wa = dict(session.execute(
        select(WhatsAppMessage.send_status, func.count())
        .where(WhatsAppMessage.sent_at >= since,
               WhatsAppMessage.is_test.is_(False))
        .group_by(WhatsAppMessage.send_status)).all())
    em = dict(session.execute(
        select(EmailMessage.send_status, func.count())
        .where(EmailMessage.sent_at >= since)
        .group_by(EmailMessage.send_status)).all())

    def count(model, *where):
        return int(session.execute(select(func.count()).select_from(model)
                                   .where(*where)).scalar() or 0)

    return {
        "whatsapp_sent": int(wa.get("sent", 0)),
        "whatsapp_failed": int(wa.get("failed", 0)) + int(wa.get("rejected", 0)),
        "whatsapp_waiting": int(wa.get("pending", 0)),
        "emails_sent": int(em.get("sent", 0)),
        "emails_failed": sum(int(v) for k, v in em.items() if k != "sent"),
        "documents_made": count(StoredDocument, StoredDocument.created_at >= since),
        "new_records": count(CSPRecord, CSPRecord.created_at >= since),
        "links_sent": count(DataRequest, DataRequest.created_at >= since),
        "links_answered": count(DataRequest, DataRequest.created_at >= since,
                                DataRequest.status == "answered"),
        "links_open_now": count(DataRequest, DataRequest.status == "open"),
    }


def what_to_fix(session) -> List[str]:
    """ZU-06: setup problems, each with where it is fixed."""
    from app.config import get_settings
    from app.models.document_template import DocumentTemplate
    s = get_settings()
    out = []
    if not s.google_sheets_csp_sheet_id:
        out.append("No main CSP sheet is connected — Setup → Connections → "
                   "Google Sheets.")
    sends_whatsapp = (s.verify_old_csps_enabled or s.msg_documents_ready
                      or s.documents_feedback_enabled)
    if sends_whatsapp and not s.whatsapp_platform_url:
        out.append("Messages are switched on but WhatsApp is not connected — "
                   "Setup → Connections → WhatsApp.")
    if not (s.smtp_host and s.smtp_username and s.smtp_password):
        out.append("No email account is connected, so documents cannot be "
                   "emailed — Setup → Connections → Email.")
    if s.emails_paused:
        out.append("Emails are paused — Settings → Email.")
    templates = list(session.execute(select(DocumentTemplate)).scalars())
    if not any(t.active for t in templates):
        out.append("No document template is active — Setup → Document "
                   "Templates.")
    if s.alerts_enabled is False:
        out.append("Alerts are off, so a failing job is not emailed — "
                   "Settings → Alerts.")
    return out


def recipients(session) -> List[str]:
    from app.config import get_settings
    from app.services import alerts
    own = sorted({e.strip().lower() for e in str(
        get_settings().health_email_to or "").split(",") if e.strip()})
    if own:
        return own
    # alerts.recipients honours alert_to first; the weekly email wants the
    # Super Admins when it has no list of its own.
    from app.models.enums import UserRole
    from app.models.workspace_member import WorkspaceMember
    return sorted(set(session.execute(select(WorkspaceMember.email).where(
        WorkspaceMember.role == UserRole.SUPER_ADMIN,
        WorkspaceMember.active.is_(True))).scalars()))


def body(n: Dict[str, int], fixes: List[str], name: str) -> str:
    lines = [f"{name}: the last 7 days", "",
             f"WhatsApps: {n['whatsapp_sent']} sent, {n['whatsapp_failed']} "
             f"failed, {n['whatsapp_waiting']} waiting for Meta's approval",
             f"Emails: {n['emails_sent']} sent, {n['emails_failed']} failed",
             f"Documents made: {n['documents_made']}",
             f"New records: {n['new_records']}",
             f"Form links: {n['links_sent']} sent, {n['links_answered']} "
             f"answered; {n['links_open_now']} still open", ""]
    if fixes:
        lines.append("What to fix in your setup:")
        lines += [f"  - {f}" for f in fixes]
    else:
        lines.append("Nothing to fix in your setup.")
    lines += ["", "Change or stop this email: Settings → Look and weekly email."]
    return "\n".join(lines)


def due(session, now: datetime) -> Optional[str]:
    """None when the email should go now, else why not."""
    from app.config import get_settings
    from app.models.audit_log import AuditLog
    from app.workers.verify_old_csps_worker import send_zone
    s = get_settings()
    if not s.health_email_on:
        return "off (Settings → Look and weekly email)"
    local = now.astimezone(send_zone())
    if DAYS[local.weekday()] != s.health_email_day or local.hour != int(
            s.health_email_hour):
        return "not the day and hour"
    last = session.execute(select(func.max(AuditLog.created_at)).where(
        AuditLog.action == ACTION)).scalar()
    if last and now - last < timedelta(days=6):
        return "already sent this week"
    return None


def run(session, now: Optional[datetime] = None, send=None) -> dict:
    from app.config import get_settings
    from app.models.audit_log import AuditLog
    from app.services import message_sender
    from app.workspace_context import current_workspace_id
    now = now or datetime.now(timezone.utc)
    s = get_settings()
    if s.test_copy or not message_sender.link_is_reachable(s.public_app_url):
        return {"skipped": "not the server (a laptop or the test copy sends "
                           "no weekly email)"}
    why = due(session, now)
    if why:
        return {"skipped": why}
    n = numbers(session, now - timedelta(days=7))
    fixes = what_to_fix(session)
    to = recipients(session)
    send = send or (lambda addr, subject, text: message_sender._send_email(
        addr, subject, text, kind="other"))
    text = body(n, fixes, s.brand_name)
    sent = []
    for addr in to:
        ok, reason = send(addr, f"{s.brand_name}: this week", text)
        if ok:
            sent.append(addr)
        else:
            logger.error("weekly_health: not sent to %s: %s", addr, reason)
    session.add(AuditLog(workspace_id=current_workspace_id(), action=ACTION,
                         resource_type="workspace",
                         resource_id=str(current_workspace_id()),
                         result="success" if sent else "failure",
                         metadata_json={"to": sent, "numbers": n,
                                        "to_fix": fixes}))
    session.commit()
    return {"sent_to": sent, "numbers": n, "to_fix": fixes}
