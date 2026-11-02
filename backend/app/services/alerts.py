"""
CSP DocMaker — alerts to the Super Admins (No. 173)

Failures used to show only on screens: nobody was told. Every
ALERT_MINUTES this looks for problems and emails the workspace's Super
Admins — once per problem, again every ALERT_REPEAT_HOURS while it lasts,
and once more when it is fixed.

Problems looked for (fixed rules):
  sheet:<source>  a sheet the app reads is stuck or its last read failed
                  (the Context table's red states)
  agent:<key>     an agent failed ALERT_AGENT_FAILURES runs in a row
  whatsapp        in the last hour at least ALERT_WHATSAPP_FAILURES
                  WhatsApps failed and more failed than went

What was sent and when is in audit_logs (alert_sent / alert_resolved,
resource = the problem key), which is also how a repeat is held back. Only
on the server (public PUBLIC_APP_URL), 8 am – 8 pm; EMAILS_PAUSED holds
these like any email.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

SENT = "alert_sent"
RESOLVED = "alert_resolved"


@dataclass
class Problem:
    key: str
    title: str
    detail: str


def problems(session, settings, now: Optional[datetime] = None) -> List[Problem]:
    """What is wrong right now."""
    from app.models.agent import AgentState
    from app.models.whatsapp_message import SEND_FAILED, SEND_SENT, WhatsAppMessage
    from app.services import field_quality

    now = now or datetime.now(timezone.utc)
    found = []
    for badge in field_quality.freshness(session, settings, now=now,
                                         with_errors=True):
        if badge["status"] in ("stuck", "failed"):
            since = badge["minutes_since_success"]
            found.append(Problem(
                key=f"sheet:{badge['source']}",
                title=f"{badge['label']}: {badge['status']}",
                detail=(f"The {badge['label']} has not been read "
                        + (f"for {since} minutes" if since is not None else "yet")
                        + (f". Last error: {badge['error']}" if badge.get("error") else "")
                        + ". Admin → Setup → Data quality → Context.")))

    for state in session.execute(select(AgentState).where(
            AgentState.consecutive_failures >= settings.alert_agent_failures)
    ).scalars():
        found.append(Problem(
            key=f"agent:{state.agent_key}",
            title=f"The {state.agent_key} agent keeps failing",
            detail=(f"{state.consecutive_failures} runs in a row failed. Last: "
                    f"{(state.last_summary or '')[:200]}. Admin → Agents.")))

    hour = now - timedelta(hours=1)
    counts = dict(session.execute(
        select(WhatsAppMessage.send_status, func.count())
        .where(WhatsAppMessage.sent_at >= hour)
        .group_by(WhatsAppMessage.send_status)).all())
    failed, sent = counts.get(SEND_FAILED, 0), counts.get(SEND_SENT, 0)
    if failed >= settings.alert_whatsapp_failures and failed > sent:
        found.append(Problem(
            key="whatsapp",
            title="WhatsApp messages are failing",
            detail=(f"In the last hour {failed} WhatsApp(s) failed and {sent} "
                    f"went. Admin → WhatsApp messages (filter: not sent).")))
    return found


def _last(session, keys: List[str]) -> Dict[str, AuditLog]:
    """The newest alert_sent / alert_resolved row per problem key."""
    if not keys:
        return {}
    rows = session.execute(
        select(AuditLog).where(AuditLog.action.in_((SENT, RESOLVED)),
                               AuditLog.resource_type == "alert",
                               AuditLog.resource_id.in_(keys))
        .order_by(AuditLog.created_at)).scalars().all()
    return {r.resource_id: r for r in rows}


def open_keys(session) -> List[str]:
    """Problems an alert went out for and no 'fixed' email followed."""
    rows = session.execute(
        select(AuditLog).where(AuditLog.action.in_((SENT, RESOLVED)),
                               AuditLog.resource_type == "alert")
        .order_by(AuditLog.created_at)).scalars().all()
    last = {}
    for r in rows:
        last[r.resource_id] = r.action
    return [k for k, action in last.items() if action == SENT]


def recipients(session) -> List[str]:
    from app.models.enums import UserRole
    from app.models.workspace_member import WorkspaceMember

    return sorted(set(session.execute(select(WorkspaceMember.email).where(
        WorkspaceMember.role == UserRole.SUPER_ADMIN,
        WorkspaceMember.active.is_(True))).scalars()))


def run(session, settings, send, now: Optional[datetime] = None) -> dict:
    """Email what is new, still open after the repeat time, or fixed.

    send(to, subject, body) -> (ok, why) — message_sender._send_email on the
    server; a list in the tests.
    """
    now = now or datetime.now(timezone.utc)
    current = problems(session, settings, now)
    last = _last(session, [p.key for p in current])
    repeat = timedelta(hours=settings.alert_repeat_hours)

    due = []
    for p in current:
        prev = last.get(p.key)
        if (prev is None or prev.action == RESOLVED
                or now - prev.created_at >= repeat):
            due.append(p)
    fixed = [k for k in open_keys(session) if k not in {p.key for p in current}]
    if not due and not fixed:
        return {"problems": len(current), "sent": 0, "fixed": 0}

    to = recipients(session)
    if not to:
        logger.error("alerts: %d problem(s) but no Super Admin to tell",
                     len(due))
        return {"problems": len(current), "sent": 0, "fixed": 0,
                "skipped": "no Super Admin in this workspace"}

    sent = 0
    for p in due:
        body = (f"{p.title}\n\n{p.detail}\n\n"
                f"You will be told again in {settings.alert_repeat_hours} hours "
                f"if it is still wrong, and once it is fixed.\n— CSP DocMaker")
        oks = [send(addr, f"CSP DocMaker alert: {p.title}", body)[0] for addr in to]
        if any(oks):
            sent += 1
            # The run's own time, so the repeat wait is measured from it.
            session.add(AuditLog(action=SENT, resource_type="alert",
                                 resource_id=p.key, result="success",
                                 created_at=now,
                                 metadata_json={"title": p.title, "to": to,
                                                "detail": p.detail[:500]}))
        else:
            logger.error("alerts: the alert '%s' could not be emailed to "
                         "anyone — tried again next run", p.title)
    for key in fixed:
        body = (f"Fixed: the problem '{key}' is no longer seen.\n— CSP DocMaker")
        oks = [send(addr, f"CSP DocMaker: fixed ({key})", body)[0] for addr in to]
        if any(oks):
            session.add(AuditLog(action=RESOLVED, resource_type="alert",
                                 resource_id=key, result="success",
                                 created_at=now,
                                 metadata_json={"to": to}))
    session.commit()
    logger.info("alerts: %d problem(s), %d alert(s) sent, %d fixed",
                len(current), sent, len(fixed))
    return {"problems": len(current), "sent": sent, "fixed": len(fixed)}
