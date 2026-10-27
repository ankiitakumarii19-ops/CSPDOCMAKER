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
bounced, is a bad number / address for that CSP. A bad WhatsApp number is
first tried on the CSP's ALTERNATE number (No. 152: the second number in
their mobile cell, else their Zoho Lead's alternate / WhatsApp number); if
that reaches the phone, it replaces the old number in CSPDATA. With no
alternate, or none that works, the CSP is asked through the OTHER channel
(the details form shows their mobile and email), once per bad value. When the record has a different number /
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
            "applied": s.applied or [],
            "note": s.note or "",
            "automatic": s.field in ("ao", "rbo_name"),
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
    from app.models.whatsapp_message import WhatsAppMessage
    from app.services import message_log

    fixes = session.execute(select(ContactFix)).scalars().all()
    have = {(f.csp_id, f.problem, f.bad_value) for f in fixes}
    # An alternate number tried for a fix is that fix's business, not a
    # problem of its own.
    tried = {(f.csp_id, n) for f in fixes for n in (f.alternates_tried or [])}
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
        # "Did not reach the phone", or no delivery after 24 hours.
        if (phone and (csp_id, phone) not in tried
                and message_log.stage(m) == message_log.NOT_RECEIVED):
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


def resend_documents_email(session, record) -> tuple:
    """The CSP's stored documents, emailed again to the address on their
    record. (ok, note, sent): ok None = waiting (emails paused)."""
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


def _resend_documents_whatsapp(session, fix: ContactFix, record,
                               mobile: Optional[str] = None) -> tuple:
    from app.models.processing_job import ProcessingJob
    from app.services import documents_whatsapp
    job = session.execute(
        select(ProcessingJob).where(ProcessingJob.csp_id == record.csp_id)
        .order_by(ProcessingJob.created_at.desc())).scalars().first()
    docs = _documents(session, record.csp_id)
    if job is None or not docs:
        return True, "nothing to send again (no documents on record)", False
    outcome = documents_whatsapp.notify(session, record, job,
                                        [label for label, _ in docs],
                                        mobile=mobile)
    if outcome.get("status") == "sent":
        return True, "documents WhatsApp sent again to the new number", True
    if outcome.get("status") == "skipped":
        return None, f"waiting: {outcome.get('reason', '')}", False
    return False, f"the WhatsApp failed again: {outcome.get('reason', '')}", False


def _numbers(cell) -> List[str]:
    """Every usable mobile number in a sheet cell, in order."""
    from app.services.alert_composer import _SEPARATORS, normalize_mobile
    out = []
    for part in _SEPARATORS.split(cell or ""):
        n = normalize_mobile(part)
        if n and n not in out:
            out.append(n)
    return out


def _zoho_numbers(session, record) -> List[str]:
    """The Zoho Lead's mobile / alternate / WhatsApp numbers (Eko only).
    Never raises: a Zoho failure means no Zoho alternates, and is logged."""
    from app.services import zoho_client, zoho_fill
    if not zoho_client.is_configured() or not zoho_fill._is_eko(session):
        return []
    try:
        lead = zoho_client.find_lead(record.mobile or "", record.name or "",
                                     record.branch_code or "")
    except Exception as e:
        logger.error("feedback_loops: Zoho search for %s's alternate number "
                     "failed: %s: %s", record.csp_id, type(e).__name__, e,
                     exc_info=True)
        return []
    out = []
    # A Lead names them Phone / Mobile / Secondary_Phone; an sbi_kiosk
    # record Mobile_Number / Alternate_Mobile_Number / WhasApp_Number.
    for key in zoho_client.LEAD_PHONE_FIELDS + zoho_client.PHONE_FIELDS:
        n = _phone((lead or {}).get(key))
        if n and n not in out:
            out.append(n)
    return out


# ---- the Calling sheet's numbers (No. 157) ------------------------------

# A Calling-sheet column is a number of the CSP's own when its heading names
# a phone and none of the other people the sheet also lists.
_PHONE_HEADING = ("mobile", "phone", "contact", "number", "whatsapp", "alternate",
                  "alt no", "alt.", "mob")
_NOT_THE_CSP = ("dc", "district coordinator", "rm", "relationship", "asm",
                "branch", "manager", "lho", "ao ", "rbo", "circle", "id",
                "code", "account", "aadhaar", "aadhar", "pan", "ifsc", "pin")

_calling_cache: Dict[str, object] = {}


def calling_phone_columns(headings: List[str]) -> List[str]:
    """The headings of the CSP's own number columns, main number first."""
    import re as _re

    def norm(h: str) -> str:
        return " " + " ".join(_re.sub(r"[^a-z0-9.]+", " ", (h or "").lower()).split()) + " "

    found = []
    for h in headings:
        n = norm(h)
        if not any(w in n for w in _PHONE_HEADING):
            continue
        if any(f" {w.strip()} " in n or n.strip().startswith(w.strip() + " ")
               for w in _NOT_THE_CSP):
            continue
        found.append(h)
    found.sort(key=lambda h: 0 if norm(h).strip() == "csp mobile number" else 1)
    return found


def _calling_numbers(record) -> List[str]:
    """The CSP's numbers in the Calling sheet (No. 157: "for the alternate
    number look in the Calling sheet"): every number in their row's own
    phone columns. Read once per run; only where CALLING_SHEET_ID is set
    (the server). Never raises: a sheet that cannot be read is logged."""
    from app.config import get_settings
    from app.services import source_sheets

    s = get_settings()
    if not s.calling_sheet_id:
        return []
    if "rows" not in _calling_cache:
        try:
            rows = source_sheets.read_rows(s.calling_sheet_id, s.calling_sheet_tab,
                                           s.calling_header_row)
        except Exception as e:
            logger.error("feedback_loops: the Calling sheet could not be read "
                         "for alternate numbers: %s: %s", type(e).__name__, e)
            rows = []
        columns = calling_phone_columns(list(rows[0].keys())) if rows else []
        _calling_cache["rows"] = {
            source_sheets.code_of(r.get("CSP ID")): [r.get(c, "") for c in columns]
            for r in rows if source_sheets.code_of(r.get("CSP ID"))}
        if rows:
            logger.info("feedback_loops: Calling sheet number columns: %s", columns)
    out = []
    for cell in _calling_cache["rows"].get(source_sheets.code_of(record.csp_id), []):
        for n in _numbers(cell):
            if n not in out:
                out.append(n)
    return out


def next_alternate(session, fix: ContactFix, record) -> Optional[str]:
    """The next number to try for this CSP, or None: the other numbers in
    their mobile cell first, then their Calling-sheet row's (No. 157), then
    their Zoho Lead's. Never the bad one, one already tried, or one with a
    problem of its own."""
    bad_numbers = {f.bad_value for f in session.execute(select(ContactFix).where(
        ContactFix.csp_id == record.csp_id,
        ContactFix.problem == WHATSAPP_UNDELIVERED)).scalars()}
    skip = bad_numbers | set(fix.alternates_tried or []) | {fix.bad_value}
    for n in _numbers(record.mobile) + _calling_numbers(record):
        if n not in skip:
            return n
    for n in _zoho_numbers(session, record):
        if n not in skip:
            return n
    return None


def _try_alternate(session, fix: ContactFix, record, number: str) -> tuple:
    """Send what did not arrive to the alternate number. (ok, note)."""
    from app.services import data_request_service as drs
    from app.services import message_sender

    from app.services import send_reason
    if fix.failed_kind == "documents_ready":
        with send_reason.because(send_reason.ALTERNATE_NUMBER):
            ok, note, _ = _resend_documents_whatsapp(session, fix, record,
                                                     mobile=number)
        return ok, note.replace("the new number", f"alternate {number}")
    try:
        channel = message_sender.choose_channel(session, kind="whatsapp")
    except message_sender.NoChannel:
        return None, "no active whatsapp channel"
    open_request = drs.open_request_for(session, record.csp_id)
    if (open_request is not None and open_request.sent_to
            and _phone(open_request.sent_to) == fix.bad_value):
        drs.cancel(session, record.csp_id,
                   "WhatsApp did not reach the phone — tried the alternate number")
    with send_reason.because(send_reason.ALTERNATE_NUMBER):
        out = message_sender.ask_for_details(session, record, channel=channel,
                                             verify=True, manual=True,
                                             mobile=number)
    if out.get("sent"):
        return True, f"data verification sent to alternate number {number}"
    reason = out.get("reason") or "not sent"
    return (False, reason) if "via" in out else (None, f"waiting: {reason}")


def _alternate_result(session, fix: ContactFix, now: datetime) -> Optional[str]:
    """What became of the message to the alternate: 'works', 'failed', or
    None while it is not known yet."""
    from app.models.whatsapp_message import WhatsAppMessage
    from app.services import message_log
    sent = [m for m in session.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.csp_id == fix.csp_id,
                                      WhatsAppMessage.sent_at >= fix.asked_at)
        .order_by(WhatsAppMessage.sent_at)).scalars()
        if _phone(m.phone) == fix.alternate]
    if not sent:
        return None
    stage = message_log.stage(sent[-1], now)
    if stage in (message_log.DELIVERED, message_log.READ):
        return "works"
    if stage in (message_log.NOT_RECEIVED, message_log.NOT_SENT):
        return "failed"
    return None


def _use_alternate(session, fix: ContactFix, record) -> tuple:
    """The alternate reached the phone: it replaces the old number in
    CSPDATA (the sheet is the source of truth) and on the record."""
    from app.services import sheet_writeback_service as wb
    ten = fix.alternate[2:] if fix.alternate.startswith("91") else fix.alternate
    try:
        written, _ = wb.write_values(record.csp_id, {"mobile": ten})
    except wb.SheetWriteError as e:
        return False, f"the alternate works, but CSPDATA could not be updated: {e}"
    if "mobile" not in written:
        return False, "the alternate works, but CSPDATA has no mobile column"
    record.mobile = ten
    logger.info("feedback_loops: %s — alternate number works; CSPDATA mobile "
                "updated", record.csp_id)
    return True, f"alternate number {ten} works — CSPDATA updated"


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

    from app.services import send_reason
    with send_reason.because(send_reason.WHATSAPP_UNREACHABLE
                             if fix.problem == WHATSAPP_UNDELIVERED
                             else send_reason.EMAIL_BOUNCED):
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
    _calling_cache.clear()        # the Calling sheet is read afresh each run
    counts = {"found": find_problems(session), "asked": 0, "corrected": 0,
              "resent": 0, "stopped": 0}
    session.commit()
    budget = max(int(settings.contact_loop_batch), 0)

    fixes = session.execute(
        select(ContactFix).where(
            ContactFix.status.in_(("open", "asked", "corrected",
                                   "trying_alternate")))
        .order_by(ContactFix.created_at)).scalars().all()
    for fix in fixes:
        record = session.execute(select(CSPRecord).where(
            CSPRecord.csp_id == fix.csp_id)).scalar_one_or_none()
        if record is None:
            fix.status, fix.note = "stopped", "the CSP is not in the records"
            counts["stopped"] += 1
            continue
        if fix.status == "trying_alternate":
            result = _alternate_result(session, fix, now)
            if result == "works":
                ok, note = _use_alternate(session, fix, record)
                if ok:
                    fix.status, fix.corrected_value = "done", fix.alternate
                    counts["corrected"] += 1
                fix.note = note
            elif result == "failed":
                fix.status = "open"
                fix.note = f"alternate {fix.alternate} is unreachable too"
                fix.alternate = None
            session.commit()
            if fix.status == "trying_alternate" or fix.status == "done":
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
            alternate = (next_alternate(session, fix, record)
                         if fix.status == "open"
                         and fix.problem == WHATSAPP_UNDELIVERED else None)
            if alternate:
                ok, note = _try_alternate(session, fix, record, alternate)
                if ok:
                    fix.status, fix.asked_at = "trying_alternate", now
                    fix.alternate = alternate
                    fix.alternates_tried = list(fix.alternates_tried or []) + [alternate]
                    fix.asked_via = "whatsapp (alternate)"
                    counts["asked"] += 1
                elif ok is False:
                    # This alternate could not be sent to: next time, the
                    # next one (or email).
                    fix.alternates_tried = list(fix.alternates_tried or []) + [alternate]
            elif fix.status == "open":
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
                    from app.services import send_reason
                    with send_reason.because(send_reason.CORRECTED):
                        ok, note, resent = resend_documents_email(session, record)
                elif (fix.problem == WHATSAPP_UNDELIVERED
                      and fix.failed_kind == "documents_ready"):
                    from app.services import send_reason
                    with send_reason.because(send_reason.CORRECTED):
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
            "alternate": f.alternate,
            "resent_at": f.resent_at.isoformat() if f.resent_at else None,
            "tries": f.tries,
            "note": f.note,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        } for f, name in rows],
    }


# ---- loop 1, automatic: the app fixes INFO itself (No. 153) -------------

def auto_fix_info(session, settings, writer=None) -> Dict[str, int]:
    """For every open suggestion about AO or RBO Name: correct INFO's AO
    block (info_writer), mark it fixed and keep what changed. Anything that
    cannot be done safely stays open with the reason, for a person."""
    from app.models.csp_record import CSPRecord
    from app.services import csp_gsheet_service, info_writer

    writer = writer or info_writer
    counts = {"fixed": 0, "left": 0}
    refresh_suggestions(session, settings.quality_suggest_min_csps)
    session.commit()
    open_ones = session.execute(select(QualitySuggestion).where(
        QualitySuggestion.status == "open",
        QualitySuggestion.field.in_(info_writer.FIELDS))).scalars().all()
    if not open_ones:
        return counts
    rows = csp_gsheet_service.read_info_sheet()
    if not rows:
        logger.error("feedback_loops.auto_fix_info: INFO could not be read — "
                     "nothing changed")
        return counts
    for s in open_ones:
        rivals = [o for o in open_ones if o is not s and o.field == s.field
                  and o.rule == s.rule and o.from_value == s.from_value]
        if rivals:
            s.note = ("people corrected it to different values ("
                      + ", ".join(sorted({s.to_value, *[o.to_value for o in rivals]}))
                      + ") — a person must decide")
            counts["left"] += 1
            continue
        records = session.execute(select(CSPRecord).where(
            CSPRecord.csp_id.in_(s.csp_ids or []))).scalars().all()
        csps = [{"branch": r.branch_name, "state": r.state,
                 "district": r.district} for r in records]
        try:
            ops = writer.plan(rows, s.field, s.from_value, s.to_value, csps)
            done = writer.apply(settings.google_sheets_csp_sheet_id,
                                settings.google_sheets_info_tab_name, ops)
        except writer.CannotFix as e:
            s.note = str(e)
            counts["left"] += 1
            continue
        except Exception as e:
            s.note = f"INFO could not be updated: {type(e).__name__}: {e}"[:500]
            logger.error("feedback_loops.auto_fix_info: %s", s.note, exc_info=True)
            counts["left"] += 1
            session.commit()
            break         # the sheet is not answering: stop for this run
        now = datetime.now(timezone.utc)
        s.status, s.fixed_at, s.decided_at = "fixed", now, now
        s.decided_by = "the app (automatic)"
        s.applied, s.note = done, "INFO corrected by the app"
        counts["fixed"] += 1
        logger.info("feedback_loops.auto_fix_info: INFO %s for %s: %r -> %r "
                    "(%d change(s))", s.field, s.rule, s.from_value,
                    s.to_value, len(done))
        session.commit()
        rows = csp_gsheet_service.read_info_sheet()   # read again after a change
    session.commit()
    return counts


def contact_status(session) -> dict:
    """In one line for the WhatsApp and Emails pages (No. 158): how many
    contact fixes are in progress / fixed / stopped, and what the ones in
    progress are waiting for (their notes, most common first)."""
    from collections import Counter
    fixes = session.execute(select(ContactFix)).scalars().all()
    busy = [f for f in fixes if f.status in
            ("open", "trying_alternate", "asked", "corrected")]
    waiting = Counter((f.note or "").split(" — ")[0][:120] for f in busy
                      if (f.note or "").startswith("waiting") or
                      f.note in ("no email address to ask on",
                                 "no usable mobile number to ask on"))
    return {
        "in_progress": len(busy),
        "fixed": sum(1 for f in fixes if f.status in ("resent", "done")),
        "stopped": sum(1 for f in fixes if f.status == "stopped"),
        "waiting": [{"note": n, "count": c} for n, c in waiting.most_common(3)],
        "found": len(fixes),
    }
