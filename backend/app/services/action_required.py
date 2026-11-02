"""
CSP DocMaker — Action Required, opened (No. 174)

One card of the RM's "Action Required" bell, in full: the CSP, what is still
missing, when it was flagged, every time they were asked (when, how, what
was sent), what they wrote back, what people sent them by hand, and — once
filled — how and when. Plus the History list (Fixed / Pending / All).

Who sees what is the bell's rule: an RM their own CSPs' cards and every
unowned one; Admins and Super Admins all of them.
"""

from typing import List, Optional

from sqlalchemy import or_, select

from app.models.rm_alert import OPEN, RESOLVED, RMAlert
from app.services import alert_service, csp_access


def visible(query, user: dict):
    """The bell's rule on a query of RMAlert."""
    if csp_access.is_admin(user):
        return query
    email = (user.get("sub") or "").strip().lower()
    return query.where(or_(RMAlert.rm_email == email, RMAlert.rm_email.is_(None)))


def may_see(alert: RMAlert, user: dict) -> bool:
    if csp_access.is_admin(user):
        return True
    email = (user.get("sub") or "").strip().lower()
    return alert.rm_email is None or alert.rm_email == email


def _labels(alert: RMAlert) -> List[str]:
    return [f.get("label") or f.get("field") or ""
            for f in (alert.details or {}).get("fields", [])]


def _iso(when) -> Optional[str]:
    return when.isoformat() if when else None


def row(alert: RMAlert, name: str = "") -> dict:
    return {
        "id": str(alert.id), "csp_id": alert.csp_id,
        "name": (alert.details or {}).get("csp_name") or name or alert.csp_id,
        "missing": _labels(alert),
        "status": "pending" if alert.status == OPEN else "fixed",
        "flagged_at": _iso(alert.created_at),
        "fixed_at": _iso(alert.resolved_at),
        "fixed_via": alert.resolved_via,
        "fixed_via_label": alert_service.VIA_LABELS.get(alert.resolved_via or "", ""),
        "fixed_note": alert.resolved_note,
    }


def history(session, user: dict, show: str = "all", q: str = "",
            limit: int = 200) -> List[dict]:
    from app.models.csp_record import CSPRecord

    query = visible(select(RMAlert, CSPRecord.name).outerjoin(
        CSPRecord, CSPRecord.csp_id == RMAlert.csp_id), user)
    if show == "fixed":
        query = query.where(RMAlert.status == RESOLVED)
    elif show == "pending":
        query = query.where(RMAlert.status == OPEN)
    from app.services import search_match

    condition = search_match.csp_condition(q)    # one way of matching (No. 175)
    if condition is not None:
        query = query.where(condition)
    rows = session.execute(query.order_by(
        RMAlert.resolved_at.desc().nullsfirst(),
        RMAlert.created_at.desc()).limit(limit)).all()
    return [row(a, name or "") for a, name in rows]


def detail(session, alert: RMAlert) -> dict:
    """Everything about this card's CSP that the RM needs to act."""
    from app.models.csp_record import CSPRecord
    from app.models.csp_reply import CspReply
    from app.models.data_request import DataRequest
    from app.models.email_message import EmailMessage
    from app.models.whatsapp_message import WhatsAppMessage
    from app.services import (field_ownership as fo, manual_messages,
                              message_log, send_reason)

    record = session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == alert.csp_id)).scalars().first()

    asked = []
    for r in session.execute(select(DataRequest).where(
            DataRequest.csp_id == alert.csp_id)
            .order_by(DataRequest.created_at.desc()).limit(20)).scalars():
        asked.append({
            "at": _iso(r.created_at), "channel": r.sent_via or "",
            "to": r.sent_to or "", "status": r.status,
            "fields": [fo.label_of(f) for f in (r.fields or [])
                       if f != "photo_url"] + (["Photograph"] if "photo_url" in (r.fields or []) else []),
            "answered_at": _iso(r.answered_at),
            "expires_at": _iso(r.expires_at),
            "error": r.delivery_error or "",
        })

    whatsapp = []
    for m in session.execute(select(WhatsAppMessage).where(
            WhatsAppMessage.csp_id == alert.csp_id)
            .order_by(WhatsAppMessage.sent_at.desc()).limit(30)).scalars():
        whatsapp.append({
            "at": _iso(m.sent_at),
            "what": m.body_text or message_log.KIND_LABEL.get(m.kind, "Message"),
            "stage": message_log.stage(m),
            "why": send_reason.label(m.sent_because),
            "sent_by": m.sent_by, "error": m.send_error or "",
        })

    emails = [{"at": _iso(e.sent_at or e.created_at), "kind": e.kind,
               "subject": e.subject, "status": e.send_status,
               "to": e.to_email, "opened_at": _iso(e.opened_at),
               "bounced": bool(e.bounced_at)}
              for e in session.execute(select(EmailMessage).where(
                  EmailMessage.csp_id == alert.csp_id)
                  .order_by(EmailMessage.created_at.desc()).limit(20)).scalars()]

    replies = []
    for r in session.execute(select(CspReply).where(
            CspReply.csp_id == alert.csp_id)
            .order_by(CspReply.created_at.desc()).limit(20)).scalars():
        replies.append({"messages": r.messages or [], "status": r.status,
                        "answer": r.reply_text or "", "sent_at": _iso(r.sent_at),
                        "by": r.decided_by})

    hold = record.send_hold if record else None
    return {
        **row(alert, record.name if record else ""),
        "rm_name": record.rm_name if record else "",
        "mobile": record.mobile if record else "",
        "email": record.email if record else "",
        "on_hold": hold or "",
        "existing": bool(record and manual_messages.is_existing(session, record)),
        "asked": asked,
        "whatsapp": whatsapp,
        "emails": emails,
        "replies": replies,
        "sent_by_people": manual_messages.sent_to(session, alert.csp_id),
        "channels": manual_messages.channels(),
    }
