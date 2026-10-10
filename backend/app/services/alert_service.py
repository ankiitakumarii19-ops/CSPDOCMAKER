"""
CSP DocMaker — RM alerts

Raising and clearing the things an RM is asked to fix.

Two properties matter more than anything else here:

  * Raising an alert is idempotent. The new-CSP worker runs every few minutes
    and will keep finding the same blocked CSP, so it must update the one open
    alert rather than filing another. Without this an RM would face hundreds
    of rows for a single CSP.

  * Alerts clear themselves. When the missing data arrives the next run
    generates the documents and closes the alert, so an RM never has to tick
    anything off a list.

An unresolved CSP has no owner, so its alert carries no rm_email and every RM
sees it — the same rule that governs who may act on such a CSP.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rm_alert import MISSING_DATA, OPEN, RESOLVED, RMAlert

logger = logging.getLogger(__name__)


def open_alert(session: Session, csp_id: str, kind: str) -> Optional[RMAlert]:
    """The open alert of this kind for this CSP, if there is one."""
    return session.execute(
        select(RMAlert).where(
            RMAlert.csp_id == csp_id,
            RMAlert.kind == kind,
            RMAlert.status == OPEN,
        )
    ).scalars().first()


def raise_alert(
    session: Session,
    csp_id: str,
    rm_email: Optional[str],
    kind: str,
    message: str,
    details: Optional[dict] = None,
) -> RMAlert:
    """Raise the alert, or refresh the one already open. Does not commit."""
    existing = open_alert(session, csp_id, kind)

    if existing is not None:
        # Keep it current: the list of what is missing shrinks as the RM fills
        # things in, and the owner can change when the sheet changes.
        changed = (
            existing.message != message
            or existing.details != details
            or existing.rm_email != rm_email
        )
        if changed:
            existing.message = message
            existing.details = details
            existing.rm_email = rm_email
            logger.info("alert_service: refreshed %s alert for CSP %s",
                        kind, csp_id)
        return existing

    alert = RMAlert(
        csp_id=csp_id, rm_email=rm_email, kind=kind,
        status=OPEN, message=message, details=details,
    )
    session.add(alert)
    logger.info(
        "alert_service: raised %s alert for CSP %s (%s)",
        kind, csp_id, rm_email or "every RM — CSP unresolved",
    )
    return alert


def resolve_alerts(session: Session, csp_id: str, kind: Optional[str] = None) -> int:
    """Close this CSP's open alerts. Returns how many were closed."""
    query = select(RMAlert).where(
        RMAlert.csp_id == csp_id, RMAlert.status == OPEN)
    if kind is not None:
        query = query.where(RMAlert.kind == kind)

    now = datetime.now(timezone.utc)
    closed = 0
    for alert in session.execute(query).scalars():
        alert.status = RESOLVED
        alert.resolved_at = now
        closed += 1

    if closed:
        logger.info("alert_service: resolved %d alert(s) for CSP %s",
                    closed, csp_id)
    return closed


def alerts_for(session: Session, rm_email: Optional[str],
               is_admin: bool = False) -> List[RMAlert]:
    """Open alerts this person should see.

    An RM sees their own, plus every unowned one — those belong to nobody, so
    anyone may act. An Admin monitors all of them.
    """
    query = select(RMAlert).where(RMAlert.status == OPEN)

    if not is_admin:
        email = (rm_email or "").strip().lower()
        query = query.where(
            (RMAlert.rm_email == email) | (RMAlert.rm_email.is_(None))
        )

    return list(session.execute(
        query.order_by(RMAlert.created_at.desc())).scalars().all())


def describe_missing(missing_check) -> tuple:
    """Turn a missing-data result into an alert message and its details.

    The same field can block several documents, so it is listed once, with
    the documents it holds up — that is what an RM needs in order to act.
    """
    by_field = {}
    for document in missing_check.documents:
        for field in document.missing_fields:
            entry = by_field.setdefault(field.field_name, {
                "field": field.field_name,
                "label": field.field_label,
                "type": field.field_type,
                "blocks": [],
            })
            entry["blocks"].append(document.document_label)

    fields = sorted(by_field.values(), key=lambda f: f["label"])
    labels = ", ".join(f["label"] for f in fields)
    message = (
        f"{missing_check.csp_name} ({missing_check.csp_id}) cannot be "
        f"documented yet — {len(fields)} detail"
        f"{'s' if len(fields) != 1 else ''} needed: {labels}."
    )
    return message, {"csp_id": missing_check.csp_id,
                     "csp_name": missing_check.csp_name,
                     "fields": fields}


__all__ = [
    "MISSING_DATA", "OPEN", "RESOLVED",
    "open_alert", "raise_alert", "resolve_alerts", "alerts_for",
    "describe_missing",
]
