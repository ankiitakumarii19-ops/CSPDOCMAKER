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


def resolve_alerts(session: Session, csp_id: str, kind: Optional[str] = None,
                   via: str = "documents_made",
                   note: str = "The documents were made") -> int:
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
        alert.resolved_via = alert.resolved_via or via
        alert.resolved_note = alert.resolved_note or note
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



# ---- No. 174: found filled, moved to History ----------------------------

# How the details were filled, as Action Required's History shows it.
VIA_LABELS = {
    "csp_form": "CSP's reply (details form)",
    "verification_agent": "Verification agent",
    "data_quality": "Data quality page",
    "sheet_editor": "App's sheet editor",
    "sheet": "Sheet edited",
    "auto_fill": "Filled automatically (INFO / Zoho / Address tab)",
    "photo": "Photo added",
    "documents_made": "Documents made",
}


def who_filled(session: Session, alert: RMAlert, record) -> tuple:
    """(via, note): the newest thing that filled one of the alert's details
    after it was raised. A sheet edit nobody recorded is the fallback."""
    from app.models.audit_log import AuditLog
    from app.models.csp_photo import CSPPhoto
    from app.models.data_request import DataRequest
    from app.models.field_provenance import FieldCorrection, FieldProvenance
    from app.services import csp_mapping

    since = alert.created_at
    names = [f.get("field") for f in (alert.details or {}).get("fields", [])]
    attrs = {csp_mapping.FIELD_TO_CSP_ATTR.get(n, n) for n in names if n}
    found = []

    for r in session.execute(select(DataRequest).where(
            DataRequest.csp_id == alert.csp_id,
            DataRequest.status == "answered",
            DataRequest.answered_at >= since)).scalars():
        if attrs & set(r.answered_values or {}) or (
                "photo" in names and r.photo_sent_at and r.photo_sent_at >= since):
            found.append((r.answered_at, "csp_form",
                          "The CSP filled in their details form"))
    for a in session.execute(select(AuditLog).where(
            AuditLog.csp_id == alert.csp_id, AuditLog.created_at >= since,
            AuditLog.action.in_(("verification_auto", "data_quality_correct"))
    )).scalars():
        m = a.metadata_json or {}
        if a.action == "verification_auto" and m.get("decision") == "wrote_answer":
            found.append((a.created_at, "verification_agent",
                          "The verification agent wrote the CSP's answer to the sheet"))
        elif a.action == "data_quality_correct":
            found.append((a.created_at, "data_quality",
                          f"Corrected on Data quality by {m.get('by') or 'someone'}"))
    for c in session.execute(select(FieldCorrection).where(
            FieldCorrection.csp_id == alert.csp_id,
            FieldCorrection.field.in_(attrs or {""}),
            FieldCorrection.created_at >= since)).scalars():
        if c.changed_via == "sheet_editor":
            found.append((c.created_at, "sheet_editor",
                          f"Changed in the app's sheet editor by {c.changed_by or 'someone'}"))
        elif c.changed_via == "csp_form":
            found.append((c.created_at, "csp_form", "The CSP filled in their details form"))
        else:
            found.append((c.created_at, "sheet", "Changed in the CSP sheet"))
    source_words = {"zoho": "the Zoho Lead", "info": "the INFO tab",
                    "address_tab": "the Address tab"}
    for p in session.execute(select(FieldProvenance).where(
            FieldProvenance.csp_id == alert.csp_id,
            FieldProvenance.field.in_(attrs or {""}),
            FieldProvenance.filled_at >= since)).scalars():
        found.append((p.filled_at, "auto_fill",
                      f"Filled automatically from {source_words.get(p.source, p.source)}"))
    if "photo" in names:
        for ph in session.execute(select(CSPPhoto).where(
                CSPPhoto.csp_id == alert.csp_id,
                CSPPhoto.updated_at >= since)).scalars():
            found.append((ph.updated_at, "photo", "A photo was added"))

    if not found:
        return "sheet", "Filled in the CSP sheet (by hand or by another job)"
    _, via, note = max(found, key=lambda f: f[0])
    return via, note


def recheck(session: Session, alerts: Optional[List[RMAlert]] = None,
            now: Optional[datetime] = None) -> int:
    """Look again at open missing-details alerts (No. 174): one whose CSP
    now has everything is closed and goes to History with how it was
    filled; the rest show only what is still missing. Does not commit.
    Returns how many were closed."""
    from app.models.csp_record import CSPRecord
    from app.models.enums import DocumentType
    from app.services import ko_level
    from app.services.missing_data_service import check_missing_data

    now = now or datetime.now(timezone.utc)
    if alerts is None:
        alerts = list(session.execute(select(RMAlert).where(
            RMAlert.status == OPEN, RMAlert.kind == MISSING_DATA)).scalars())
    closed = 0
    for alert in alerts:
        if alert.status != OPEN or alert.kind != MISSING_DATA:
            continue
        record = session.execute(select(CSPRecord).where(
            CSPRecord.csp_id == alert.csp_id)).scalars().first()
        if record is None:
            continue
        try:
            doc_types = ko_level.allowed_documents(
                record.csp_code or record.csp_id, list(DocumentType))
            missing = check_missing_data(record, doc_types)
        except Exception as e:
            # Left open: better a stale card than one closed by mistake.
            logger.error("alert_service.recheck: could not check CSP %s: "
                         "%s: %s", alert.csp_id, type(e).__name__, e,
                         exc_info=True)
            continue
        if missing.has_missing_data:
            message, details = describe_missing(missing)
            if details != alert.details:
                alert.message, alert.details = message, details
            continue
        via, note = who_filled(session, alert, record)
        alert.status, alert.resolved_at = RESOLVED, now
        alert.resolved_via, alert.resolved_note = via, note
        closed += 1
        logger.info("alert_service: CSP %s has everything now — alert "
                    "moved to History (%s)", alert.csp_id, note)
    return closed

__all__ = [
    "MISSING_DATA", "OPEN", "RESOLVED",
    "open_alert", "raise_alert", "resolve_alerts", "alerts_for", "recheck",
    "who_filled",
    "describe_missing",
]
