"""
CSP DocMaker — the feedback loops (No. 150)

Loop 1 — mapping. The corrections people make to values INFO filled in
(services/field_quality.py) are grouped: the same field, the same INFO
match ("INFO AO block, by branch 'VISARWADI'"), the same wrong value and the
same right one. Seen on QUALITY_SUGGEST_MIN_CSPS CSPs or more, that is a
suggestion to fix INFO. An Admin accepts it (the team corrects the INFO
sheet) or dismisses it. The app never writes INFO itself; it marks an
accepted suggestion FIXED once INFO is seen giving the corrected value.

Loop 2 — contact. A WhatsApp that did not reach the phone, or an email that
bounced, is a bad number / address for that CSP. The CSP is asked for the
right one through the OTHER channel (the details form shows their mobile and
email), once per bad value. When the record has a different number /
address — from that form, or typed into the sheet — what failed is sent
again: the documents email to the new address, the "documents ready"
WhatsApp to the new number. Anything else that failed (a details request)
is replaced by the ask itself.

Rules kept: nothing goes to a CSP on hold; EMAILS_PAUSED holds emails (and
does not use up a try); at most CONTACT_LOOP_BATCH sends per run; at most 3
tries per fix; never from a copy of the app that is not on a public address
(a laptop never messages a CSP). Deterministic. No AI (AI_SPEC D1).
"""

import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select

from app.models.feedback_loop import ContactFix, QualitySuggestion
from app.models.field_provenance import FieldProvenance

logger = logging.getLogger(__name__)

MAX_TRIES = 3

WHATSAPP_UNDELIVERED = "whatsapp_undelivered"
EMAIL_BOUNCED = "email_bounced"
PROBLEM_LABEL = {WHATSAPP_UNDELIVERED: "WhatsApp did not reach the phone",
                 EMAIL_BOUNCED: "Email bounced"}


# ---- loop 1: suggested INFO fixes ---------------------------------------

def refresh_suggestions(session, min_csps: int,
                        now: Optional[datetime] = None) -> Dict[str, int]:
    """Bring the suggestions up to date with the corrections recorded so
    far, and mark accepted ones fixed once INFO gives the right value."""
    now = now or datetime.now(timezone.utc)
    rows = session.execute(
        select(FieldProvenance.field, FieldProvenance.detail,
               FieldProvenance.auto_value, FieldProvenance.current_value,
               FieldProvenance.csp_id)
        .where(FieldProvenance.source == "info",
               FieldProvenance.status == "corrected")).all()
    groups: Dict[tuple, set] = {}
    for field, rule, wrong, right, csp_id in rows:
        groups.setdefault((field, rule, wrong, right), set()).add(csp_id)

    existing = {(s.field, s.rule, s.from_value, s.to_value): s
                for s in session.execute(select(QualitySuggestion)).scalars()}
    added = 0
    for key, csps in groups.items():
        if len(csps) < max(int(min_csps), 1):
            continue
        s = existing.get(key)
        if s is None:
            field, rule, wrong, right = key
            s = QualitySuggestion(field=field, rule=rule, from_value=wrong,
                                  to_value=right, csp_ids=sorted(csps))
            session.add(s)
            existing[key] = s
            added += 1
            logger.info("feedback_loops: new INFO suggestion — %s %s: %r -> "
                        "%r (%d CSPs)", field, rule, wrong, right, len(csps))
        elif set(s.csp_ids or []) != csps | set(s.csp_ids or []):
            s.csp_ids = sorted(csps | set(s.csp_ids or []))

    fixed = 0
    for s in existing.values():
        if s.status != "accepted" or s.decided_at is None:
            continue
        seen = session.execute(
            select(func.count()).select_from(FieldProvenance).where(
                FieldProvenance.source == "info",
                FieldProvenance.field == s.field,
                FieldProvenance.detail == s.rule,
                FieldProvenance.auto_value == s.to_value,
                FieldProvenance.filled_at >= s.decided_at)).scalar() or 0
        if seen:
            s.status, s.fixed_at = "fixed", now
            fixed += 1
            logger.info("feedback_loops: INFO suggestion fixed — %s %s now "
                        "gives %r", s.field, s.rule, s.to_value)
    session.flush()
    return {"added": added, "fixed": fixed}


def list_suggestions(session, status: str = "") -> List[dict]:
    from app.models.csp_record import CSPRecord
    from app.services import field_quality

    query = select(QualitySuggestion)
    if status:
        query = query.where(QualitySuggestion.status == status)
    order = {"open": 0, "accepted": 1, "fixed": 2, "dismissed": 3}
    suggestions = sorted(session.execute(query).scalars().all(),
                         key=lambda s: (order.get(s.status, 9),
                                        -len(s.csp_ids or []), s.field))
    ids = {c for s in suggestions for c in (s.csp_ids or [])}
    names = dict(session.execute(
        select(CSPRecord.csp_id, CSPRecord.name)
        .where(CSPRecord.csp_id.in_(ids))).all()) if ids else {}
    out = []
    for s in suggestions:
        # CSPs INFO still gives the wrong value to, nobody having checked.
        still = session.execute(
            select(func.count()).select_from(FieldProvenance).where(
                FieldProvenance.source == "info",
                FieldProvenance.field == s.field,
                FieldProvenance.detail == s.rule,
                FieldProvenance.auto_value == s.from_value,
                FieldProvenance.status == "auto")).scalar() or 0
        out.append({
            "id": str(s.id),
            "field": s.field,
            "label": field_quality._label(s.field),
            "rule": s.rule,
            "from_value": s.from_value,
            "to_value": s.to_value,
            "csps": [{"csp_id": c, "name": names.get(c) or ""}
                     for c in (s.csp_ids or [])],
            "still_wrong": still,
            "status": s.status,
            "decided_by": s.decided_by,
            "decided_at": s.decided_at.isoformat() if s.decided_at else None,
            "fixed_at": s.fixed_at.isoformat() if s.fixed_at else None,
        })
    return out


def decide(session, suggestion_id, action: str, by: str) -> Optional[QualitySuggestion]:
    """accept / dismiss. Returns the suggestion, or None if not found."""
    s = session.get(QualitySuggestion, suggestion_id)
    if s is None:
        return None
    if s.status == "fixed":
        return s
    s.status = "accepted" if action == "accept" else "dismissed"
    s.decided_by, s.decided_at = by, datetime.now(timezone.utc)
    return s


# ---- loop 2: contact fixes ----------------------------------------------

def _phone(value) -> str:
    from app.services.alert_composer import normalize_mobile
    return normalize_mobile(value or "")


def _email(value) -> str:
    return (value or "").strip().lower()


def find_problems(session) -> int:
    """New contact problems, one per CSP and bad number / address. A number
    that later reached the phone, or an address whose later email was
    opened, is not a problem."""
    from app.models.email_message import EmailMessage
    from app.models.whatsapp_message import DELIVERY_FAILED, WhatsAppMessage

    have = {(f.csp_id, f.problem, f.bad_value)
            for f in session.execute(select(ContactFix)).scalars()}
    found = []

    messages = session.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.csp_id.isnot(None),
                                      WhatsAppMessage.is_test.is_(False))
        .order_by(WhatsAppMessage.sent_at)).scalars().all()
    # Only the NEWEST message to each number counts: a later one that
    # reached the phone means the number works.
    latest: Dict[tuple, object] = {}
    for m in messages:
        latest[(m.csp_id, _phone(m.phone))] = m
    for (csp_id, phone), m in latest.items():
        if phone and m.delivery_status == DELIVERY_FAILED:
            found.append((csp_id, WHATSAPP_UNDELIVERED, phone, m.kind))

    emails = session.execute(
        select(EmailMessage).where(EmailMessage.csp_id.isnot(None))
        .order_by(EmailMessage.sent_at)).scalars().all()
    last_mail: Dict[tuple, object] = {}
    for e in emails:
        last_mail[(e.csp_id, _email(e.to_email))] = e
    for (csp_id, address), e in last_mail.items():
        if address and e.bounced_at is not None and e.opened_at is None:
            found.append((csp_id, EMAIL_BOUNCED, address, e.kind))

    added = 0
    for csp_id, problem, bad, kind in found:
        if (csp_id, problem, bad) in have:
            continue
        session.add(ContactFix(csp_id=csp_id, problem=problem, bad_value=bad,
                               failed_kind=kind or ""))
        have.add((csp_id, problem, bad))
        added += 1
    session.flush()
    return added


def _documents(session, csp_id: str):
    """The newest PDF of each document this CSP has, as (label, bytes)."""
    from app.models.enums import DocumentFormat
    from app.models.stored_document import StoredDocument
    from app.services.missing_data_service import document_label

    rows = session.execute(
        select(StoredDocument).where(
            StoredDocument.csp_id == csp_id,
            StoredDocument.file_format == DocumentFormat.PDF)
        .order_by(StoredDocument.document_type,
                  StoredDocument.version.desc())).scalars().all()
    newest = {}
    for r in rows:
        newest.setdefault(r.document_type, r)
    return [(document_label(t), r) for t, r in newest.items()]


def _resend_documents_email(session, fix: ContactFix, record) -> tuple:
    from app.services import email_service
    if email_service.paused():
        return None, "waiting: emails are paused (EMAILS_PAUSED)", False
    docs = _documents(session, record.csp_id)
    if not docs:
        return True, "no stored documents to send again", False
    folder = tempfile.mkdtemp(prefix="contact-loop-")
    paths = []
    try:
        for label, row in docs:
            path = os.path.join(folder, row.filename or f"{label}.pdf")
            with open(path, "wb") as f:
                f.write(row.file_data)
            paths.append(path)
        ok = email_service.send_documents_email(
            to_email=record.email, csp_name=record.name or record.csp_id,
            csp_id=record.csp_id, doc_names=[label for label, _ in docs],
            doc_filepaths=paths)
    finally:
        for p in paths:
            try:
                os.remove(p)
            except OSError as e:
                logger.warning("feedback_loops: could not remove %s: %s", p, e)
        try:
            os.rmdir(folder)
        except OSError as e:
            logger.warning("feedback_loops: could not remove %s: %s", folder, e)
    if ok:
        return True, f"documents emailed again to {record.email}", True
    return False, "the documents email failed again — see the Emails page", False


def _resend_documents_whatsapp(session, fix: ContactFix, record) -> tuple:
    from app.models.processing_job import ProcessingJob
    from app.services import documents_whatsapp
    job = session.execute(
        select(ProcessingJob).where(ProcessingJob.csp_id == record.csp_id)
        .order_by(ProcessingJob.created_at.desc())).scalars().first()
    docs = _documents(session, record.csp_id)
    if job is None or not docs:
        return True, "nothing to send again (no documents on record)", False
    outcome = documents_whatsapp.notify(session, record, job,
                                        [label for label, _ in docs])
    if outcome.get("status") == "sent":
        return True, "documents WhatsApp sent again to the new number", True
    if outcome.get("status") == "skipped":
        return None, f"waiting: {outcome.get('reason', '')}", False
    return False, f"the WhatsApp failed again: {outcome.get('reason', '')}", False


def _ask(session, fix: ContactFix, record) -> tuple:
    """Ask on the other channel. (True, note) asked; (None, note) waiting
    without using a try; (False, note) tried and failed."""
    from app.services import data_request_service as drs
    from app.services import message_sender
    from app.services import whatsapp_platform as wa

    if fix.problem == WHATSAPP_UNDELIVERED:
        if not _email(record.email):
            return None, "no email address to ask on"
        kind, via = "email", "email"
    else:
        if not wa.phone_for_whatsapp(record.mobile or ""):
            return None, "no usable mobile number to ask on"
        kind, via = "whatsapp", "whatsapp"
    try:
        channel = message_sender.choose_channel(session, kind=kind)
    except message_sender.NoChannel:
        return None, f"no active {kind} channel to ask on"

    # The open request whose link went to the bad number / address never
    # reached them: close it, so a fresh link goes on the other channel.
    open_request = drs.open_request_for(session, record.csp_id)
    if open_request is not None and open_request.sent_to:
        sent_to = (_phone(open_request.sent_to)
                   if fix.problem == WHATSAPP_UNDELIVERED
                   else _email(open_request.sent_to))
        if sent_to == fix.bad_value:
            drs.cancel(session, record.csp_id,
                       f"{PROBLEM_LABEL[fix.problem]} — asked again by {via}")

    out = message_sender.ask_for_details(session, record, channel=channel,
                                         verify=True, allow_email=True)
    if out.get("sent"):
        return True, f"asked by {via} for the right " + (
            "mobile number" if fix.problem == WHATSAPP_UNDELIVERED
            else "email address")
    reason = out.get("reason") or "not sent"
    if "via" in out:                 # it was really tried, and failed
        return False, reason
    return None, f"waiting: {reason}"


def run(session, settings, now: Optional[datetime] = None) -> Dict[str, int]:
    """One pass of the contact loop for the workspace in force."""
    from app.models.csp_record import CSPRecord

    now = now or datetime.now(timezone.utc)
    counts = {"found": find_problems(session), "asked": 0, "corrected": 0,
              "resent": 0, "stopped": 0}
    session.commit()
    budget = max(int(settings.contact_loop_batch), 0)

    fixes = session.execute(
        select(ContactFix).where(
            ContactFix.status.in_(("open", "asked", "corrected")))
        .order_by(ContactFix.created_at)).scalars().all()
    for fix in fixes:
        record = session.execute(select(CSPRecord).where(
            CSPRecord.csp_id == fix.csp_id)).scalar_one_or_none()
        if record is None:
            fix.status, fix.note = "stopped", "the CSP is not in the records"
            counts["stopped"] += 1
            continue
        current = (_phone(record.mobile) if fix.problem == WHATSAPP_UNDELIVERED
                   else _email(record.email))
        if fix.status in ("open", "asked") and current and current != fix.bad_value:
            fix.status, fix.corrected_value = "corrected", current
            fix.note = "corrected in the records"
            counts["corrected"] += 1
        if fix.status == "open" and record.send_hold:
            fix.note = f"waiting: {record.send_hold}"
            continue
        if fix.status not in ("open", "corrected") or budget <= 0:
            continue

        try:
            if fix.status == "open":
                ok, note = _ask(session, fix, record)
                if ok:
                    fix.status, fix.asked_at = "asked", now
                    fix.asked_via = ("email" if fix.problem == WHATSAPP_UNDELIVERED
                                     else "whatsapp")
                    counts["asked"] += 1
            else:
                if record.send_hold:
                    ok, note, resent = None, f"waiting: {record.send_hold}", False
                elif fix.problem == EMAIL_BOUNCED and fix.failed_kind == "documents":
                    ok, note, resent = _resend_documents_email(session, fix, record)
                elif (fix.problem == WHATSAPP_UNDELIVERED
                      and fix.failed_kind == "documents_ready"):
                    ok, note, resent = _resend_documents_whatsapp(
                        session, fix, record)
                else:
                    ok, note, resent = True, (
                        "nothing to send again — the ask on the other "
                        "channel replaced it"), False
                if ok:
                    fix.status = "resent" if resent else "done"
                    fix.resent_at = now if resent else None
                    counts["resent"] += int(resent)
        except Exception as e:
            session.rollback()
            ok, note = False, f"{type(e).__name__}: {e}"[:500]
            logger.error("feedback_loops: contact fix for %s failed: %s",
                         fix.csp_id, note, exc_info=True)
            fix = session.get(ContactFix, fix.id)

        fix.note = note
        if ok is not None:
            budget -= 1
        if ok is False:
            fix.tries += 1
            if fix.tries >= MAX_TRIES:
                fix.status = "stopped"
                fix.note = f"stopped after {MAX_TRIES} tries — {note}"
                counts["stopped"] += 1
        session.commit()
    session.commit()
    logger.info("feedback_loops.run: %s", counts)
    return counts


def list_contact_fixes(session, status: str = "", limit: int = 100) -> dict:
    from app.models.csp_record import CSPRecord
    query = (select(ContactFix, CSPRecord.name)
             .outerjoin(CSPRecord, CSPRecord.csp_id == ContactFix.csp_id))
    if status:
        query = query.where(ContactFix.status == status)
    rows = session.execute(query.order_by(ContactFix.updated_at.desc())
                           .limit(limit)).all()
    totals = dict(session.execute(
        select(ContactFix.status, func.count()).group_by(ContactFix.status)).all())
    return {
        "totals": totals,
        "fixes": [{
            "csp_id": f.csp_id,
            "csp_name": name or "",
            "problem": f.problem,
            "problem_label": PROBLEM_LABEL.get(f.problem, f.problem),
            "bad_value": f.bad_value,
            "failed_kind": f.failed_kind,
            "status": f.status,
            "asked_via": f.asked_via,
            "asked_at": f.asked_at.isoformat() if f.asked_at else None,
            "corrected_value": f.corrected_value,
            "resent_at": f.resent_at.isoformat() if f.resent_at else None,
            "tries": f.tries,
            "note": f.note,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        } for f, name in rows],
    }
