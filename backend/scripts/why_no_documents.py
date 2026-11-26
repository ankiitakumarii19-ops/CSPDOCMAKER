r"""Why did a CSP who filled the form not get their documents? (PROJECT-REGISTER No. 259)

    python scripts/why_no_documents.py 1A852542      # one CSP, step by step
    python scripts/why_no_documents.py               # everyone: who filled the
                                                     # form and got no documents
                                                     # email, grouped by reason
    python scripts/why_no_documents.py --codes       # ... with the CSP codes

Read-only: it changes nothing, sends nothing.

The path a CSP takes after filling the form (csp_form_router.submit_form ->
new_csp_worker.process_new_csps):

  1. The answer is saved and written to the sheet.
  2. An old CSP copied in from the Calling sheet is put in line for its
     documents (auto_enrolled_at) - ONLY if the sheet write worked.
     A NEW CSP is in line already.
  3. Every few minutes the new-CSP job takes everyone in line: on hold ->
     skipped; anything a document needs still missing -> RM alert, waits;
     emails paused -> waits; otherwise documents made, stored and emailed.

Each CSP is put at the first step it did not get past.
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.csp_record import CSPRecord  # noqa: E402
from app.models.data_request import ANSWERED, DataRequest  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.workspace_context import workspace  # noqa: E402

EKO = "sbi-kiosk-csp"

# The reasons, in the order a CSP meets them.
NO_RECORD = "A. no CSP record with this code"
HOLD = "B. on hold (inactive / not live) - nothing goes out"
OLD = "C. was in CSPDATA before the import - owner's rule: never mailed"
SHEET_FAILED = ("D. form saved, but writing it to the sheet failed - so the "
                "CSP was never put in line for documents (BUG)")
NOT_ENROLLED = "E. form saved, but never put in line for documents (BUG)"
AUTO_OFF = "F. new CSP, but 'make documents by itself' is switched off"
MISSING = "G. in line, but something a document needs is still missing (RM alerted)"
PAUSED = "H. in line, nothing missing - waiting because emails are paused"
MAKING_FAILS = "I. in line, nothing missing - making the documents fails"
WAITING = "J. in line, nothing missing - the next run should send them"
EMAIL_FAILED = "K. documents made, but the email did not go"
NO_EMAIL = "L. documents made, no email was ever tried"


def _when(d):
    return d.strftime("%d %b %Y %H:%M UTC") if d else "-"


def facts(db, record, imported, s):
    """(reason, [lines]) for one CSP that filled the form."""
    from app.models.email_job import EmailJob
    from app.models.enums import DocumentType, EmailStatus
    from app.models.processing_job import ProcessingJob
    from app.models.rm_alert import OPEN, RMAlert
    from app.services import email_service, ko_level
    from app.services.missing_data_service import check_missing_data

    lines = []
    code = (record.csp_code or record.csp_id or "").upper()
    lines.append(f"origin={record.origin}  hold={record.send_hold or '-'}  "
                 f"imported_as={imported.get(code) or '-'}")
    lines.append(f"put in line for documents: {_when(record.auto_enrolled_at)} "
                 f"by {record.auto_enrolled_by or '-'}")
    lines.append(f"documents made (processed): {_when(record.new_csp_processed_at)}")
    lines.append(f"email on record: {record.email or '(blank)'}")

    forms = db.execute(select(DataRequest).where(
        func.upper(DataRequest.csp_id) == record.csp_id.upper())
        .order_by(DataRequest.created_at)).scalars().all()
    last_answer = None
    for r in forms:
        lines.append(f"form {r.created_at:%d %b %H:%M}: {r.status}"
                     f"{' at ' + _when(r.answered_at) if r.answered_at else ''}"
                     f"{'  SHEET ERROR: ' + r.sheet_error if r.sheet_error else ''}")
        if r.status == ANSWERED:
            last_answer = r

    jobs = db.execute(select(ProcessingJob).where(
        ProcessingJob.csp_id == record.csp_id)
        .order_by(ProcessingJob.created_at)).scalars().all()
    emails = []
    for j in jobs:
        lines.append(f"job {j.job_id} {j.created_at:%d %b %H:%M}: "
                     f"{getattr(j.current_state, 'value', j.current_state)}"
                     f"{'  ' + j.error_message if j.error_message else ''}")
        for e in db.execute(select(EmailJob).where(
                EmailJob.processing_job_id == j.id)).scalars():
            emails.append(e)
            lines.append(f"   email to {e.recipient}: "
                         f"{getattr(e.status, 'value', e.status)}"
                         f"{'  ' + e.failure_reason if e.failure_reason else ''}")
    for a in db.execute(select(RMAlert).where(
            RMAlert.csp_id == record.csp_id, RMAlert.status == OPEN)).scalars():
        lines.append(f"open RM alert ({a.kind}, to {a.rm_email or '-'}): {a.message}")

    if record.send_hold:
        return HOLD, lines
    if (record.origin or "") == "baseline" and code not in imported:
        return OLD, lines

    if record.new_csp_processed_at is not None:
        if any(e.status == EmailStatus.SENT for e in emails):
            return None, lines            # it did go
        return (EMAIL_FAILED if emails else NO_EMAIL), lines

    in_line = ((record.origin == "new" and s.auto_documents_new)
               or record.auto_enrolled_at is not None)
    if not in_line:
        if record.origin == "new":
            return AUTO_OFF, lines
        if last_answer is not None and last_answer.sheet_error:
            return SHEET_FAILED, lines
        return NOT_ENROLLED, lines

    doc_types = ko_level.allowed_documents(code, list(DocumentType))
    missing = check_missing_data(record, doc_types)
    if missing.has_missing_data:
        from app.services import alert_service
        message, _ = alert_service.describe_missing(missing)
        lines.append(f"still missing now: {message}")
        return MISSING, lines
    if email_service.paused():
        lines.append(f"emails paused: {email_service.paused_reason()}")
        return PAUSED, lines
    if jobs and jobs[-1].error_message:
        return MAKING_FAILS, lines
    return WAITING, lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("code", nargs="?", default="", help="one CSP code")
    ap.add_argument("--workspace", default=EKO)
    ap.add_argument("--codes", action="store_true",
                    help="list the CSP codes under each reason")
    a = ap.parse_args()

    s = get_settings()
    engine = create_engine(s.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as db:
        ws = db.execute(select(Workspace).where(
            Workspace.slug == a.workspace)).scalar_one_or_none()
    if ws is None:
        print(f"No workspace {a.workspace!r}.")
        return 1

    from app.models.source_sheet import SourceSheetState

    with workspace(ws.id), Session(engine) as db:
        s = get_settings()
        imported = {(c or "").upper(): how for c, how in db.execute(
            select(SourceSheetState.csp_code, SourceSheetState.imported_as)
            .where(SourceSheetState.imported_as.isnot(None)))}

        if a.code:
            code = "".join(a.code.split()).upper()
            record = db.execute(select(CSPRecord).where(or_code(code))).scalars().first()
            if record is None:
                print(f"{code}: {NO_RECORD}")
                return 0
            reason, lines = facts(db, record, imported, s)
            print(f"{record.csp_id}  {record.name or ''}")
            for line in lines:
                print("  " + line)
            print()
            print("RESULT: " + (reason or "the documents email WENT - nothing stuck"))
            return 0

        answered = db.execute(select(func.upper(DataRequest.csp_id)).where(
            DataRequest.status == ANSWERED).distinct()).scalars().all()
        groups = defaultdict(list)
        for code in sorted(set(answered)):
            record = db.execute(select(CSPRecord).where(or_code(code))).scalars().first()
            if record is None:
                groups[NO_RECORD].append(code)
                continue
            reason, _ = facts(db, record, imported, s)
            if reason:
                groups[reason].append(record.csp_id)
        total = sum(len(v) for v in groups.values())
        print(f"Filled the form: {len(set(answered))} CSP(s); "
              f"no documents email: {total}")
        for reason in sorted(groups):
            print(f"  {len(groups[reason]):5d}  {reason}")
            if a.codes:
                print("         " + ", ".join(groups[reason]))
    return 0


def or_code(code):
    from sqlalchemy import or_
    return or_(func.upper(CSPRecord.csp_id) == code,
               func.upper(CSPRecord.csp_code) == code)


if __name__ == "__main__":
    sys.exit(main())
