"""Send the "how to fill the details form" video on WhatsApp (No. 209, 254).

To: every CSP that has not yet RECEIVED its documents by email (No. 254-255)
- KO or Sub-KO, sent a form link or not, form filled or not. One send per CSP
code: the code is the unique key, so a code seen twice is sent to once. Never a CSP that was in CSPDATA
before the Calling / Lead import, never one on hold, never one without a
usable mobile, never twice (a CSP who already got this video is skipped on
every later run).

The video goes inside its own WhatsApp wording (template TEMPLATE_NAME, with a
video header), which Meta must approve once. Run on the SERVER:

    docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \\
        exec api python scripts/send_guide_video.py                  # who would get it; nothing sent
    ... exec api python scripts/send_guide_video.py --create-template  # once: ask Meta to approve
    ... exec api python scripts/send_guide_video.py --send --by you@eko.co.in

Without --send nothing is sent. --send refuses until Meta shows the wording
APPROVED. Every send is logged in the CSP's WhatsApp history ("sent because:
How-to-fill-the-form video", with who sent it) and in the audit log.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import telemetry  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models.csp_record import CSPRecord  # noqa: E402
from app.models.data_request import DataRequest  # noqa: E402
from app.models.whatsapp_message import KIND_OTHER, WhatsAppMessage  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.workspace_context import workspace  # noqa: E402

EKO = "sbi-kiosk-csp"
VIDEO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "app", "assets", "guide", "csp-form-guide.mp4")
TEMPLATE_NAME = "cspdocmaker_form_guide_video_v1"
# Kept fixed: Meta approves this exact wording once. {{1}} = the CSP's name.
TEMPLATE_BODY = (
    "Namaste {{1}}, Eko ki taraf se: is video mein dekhiye ki apni details ka "
    "form kaise bharna hai. WhatsApp par bheja gaya form link kholiye, details "
    "check kijiye, galat ho to sahi kijiye, apni photo daaliye aur Submit "
    "kijiye. Dhanyavaad, Eko Bharat Ventures")


def masked(phone: str) -> str:
    return phone[:4] + "*" * max(len(phone) - 6, 0) + phone[-2:]


def recipients(db):
    """(record, phone, link_sent_at or None) for everyone who should get the
    video, plus {reason: count} for everyone left out.

    No. 254-255: every CSP that has not yet received its documents - KO or
    Sub-KO, form link or not, form filled or not. Still never: a CSP that was in
    CSPDATA before the Calling / Lead import (owner's rule D14), one on
    hold, one without a usable number, or one that already got the video."""
    from app.models.email_job import EmailJob
    from app.models.enums import EmailStatus
    from app.models.processing_job import ProcessingJob
    from app.models.source_sheet import SourceSheetState
    from app.services import send_reason
    from app.services import whatsapp_platform as wa
    from app.models.email_message import KIND_DOCUMENTS, EmailMessage

    asked = dict(db.execute(
        select(DataRequest.csp_id, func.max(DataRequest.created_at))
        .where(DataRequest.sent_via.is_not(None))
        .group_by(DataRequest.csp_id)).all())
    already = set(db.execute(select(WhatsAppMessage.csp_id).where(
        WhatsAppMessage.sent_because == send_reason.GUIDE_VIDEO,
        WhatsAppMessage.send_status == "sent")).scalars())
    imported = set(db.execute(select(SourceSheetState.csp_code).where(
        SourceSheetState.imported_as.is_not(None))).scalars())
    # Received: documents emailed to the CSP - an email job that went out,
    # or a documents email that was sent and did not bounce. Documents made
    # but not emailed yet are NOT received (No. 255).
    received = set(db.execute(
        select(ProcessingJob.csp_id)
        .join(EmailJob, EmailJob.processing_job_id == ProcessingJob.id)
        .where(EmailJob.status == EmailStatus.SENT)).scalars())
    received |= set(db.execute(select(EmailMessage.csp_id).where(
        EmailMessage.kind == KIND_DOCUMENTS,
        EmailMessage.send_status == "sent",
        EmailMessage.bounced_at.is_(None))).scalars())

    chosen, left_out, seen = [], {}, set()

    def skip(why):
        left_out[why] = left_out.get(why, 0) + 1

    def key_of(r):
        return (r.csp_code or r.csp_id or "").strip().upper()

    records = db.execute(select(CSPRecord).order_by(CSPRecord.csp_id)).scalars().all()
    # The CSP code is the unique key: documents received under any row of a
    # code count for the code.
    received_codes = {key_of(r) for r in records if r.csp_id in received}

    for r in records:
        code = (r.csp_code or r.csp_id or "").strip()
        key = code.upper()
        if key in seen:
            skip("same CSP code twice (sent once)")
        elif (r.origin or "") == "baseline" and code not in imported:
            skip("in CSPDATA before the import (never messaged)")
        elif r.csp_id in received or key in received_codes:
            skip("already received documents")
        elif (r.send_hold or "").strip():
            skip("on hold")
        elif r.csp_id in already:
            skip("already got this video")
        elif not wa.phone_for_whatsapp(r.mobile or ""):
            skip("no usable mobile number")
        else:
            seen.add(key)
            chosen.append((r, wa.phone_for_whatsapp(r.mobile), asked.get(r.csp_id)))
    return chosen, left_out


def breakdown(db, chosen):
    """Who the chosen are, as (label, count) lines for the dry run."""
    filled = set(db.execute(select(DataRequest.csp_id).where(
        DataRequest.status == "answered")).scalars())
    rows = [(r, at) for r, _, at in chosen]
    count = lambda test: sum(1 for r, at in rows if test(r, at))  # noqa: E731
    return [
        ("new CSPs (came after the first sync)", count(lambda r, at: r.origin == "new")),
        ("Calling-sheet copies (old CSPs copied in by the import)",
         count(lambda r, at: r.origin != "new")),
        ("KOs (8-character code)", count(lambda r, at: len((r.csp_code or r.csp_id).strip()) == 8)),
        ("Sub-KOs", count(lambda r, at: len((r.csp_code or r.csp_id).strip()) != 8)),
        ("sent a form link", count(lambda r, at: at is not None)),
        ("never sent a form link", count(lambda r, at: at is None)),
        ("already filled the form", count(lambda r, at: r.csp_id in filled)),
    ]


def _templates(text: str):
    """The platform lists templates as JSON objects one after another."""
    import json
    decoder, i, out = json.JSONDecoder(), 0, []
    while True:
        i = text.find("{", i)
        if i < 0:
            return out
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        i = end


def template_status() -> str:
    """APPROVED / PENDING / REJECTED / NOT LISTED / unknown (...).
    NOT LISTED can also mean the platform's list stopped at 100 (No. 189)."""
    from app.services import whatsapp_platform as wa
    try:
        answer = wa.call_tool("list_meta_templates", {})
    except wa.WhatsAppPlatformError as e:
        return f"unknown ({e})"
    items = answer.get("templates") or answer.get("data") or _templates(answer.get("text", ""))
    for t in items:
        if t.get("name") == TEMPLATE_NAME:
            return str(t.get("status", "?")).upper()
    return "NOT LISTED"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default=EKO)
    ap.add_argument("--create-template", action="store_true",
                    help="submit the video wording to Meta for approval (once)")
    ap.add_argument("--send", action="store_true", help="really send")
    ap.add_argument("--by", default="", help="your email (recorded as the sender)")
    ap.add_argument("--only", nargs="*", default=[], help="only these CSP codes")
    ap.add_argument("--limit", type=int, default=0, help="send to at most this many")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between sends")
    a = ap.parse_args()
    telemetry.setup("cspdocmaker-script", "WARNING")

    from app.services import message_log, send_reason
    from app.services import whatsapp_platform as wa
    from app.services.manual_messages import _audit
    from app.services.message_sender import link_is_reachable

    s = get_settings()
    if not os.path.exists(VIDEO):
        print(f"The video is missing: {VIDEO}")
        return 1

    if a.create_template:
        if s.test_copy:
            print("TEST_COPY: nothing is sent to WhatsApp from the test copy.")
            return 1
        status = template_status()
        if status != "NOT LISTED" and not status.startswith("unknown"):
            print(f"{TEMPLATE_NAME} already exists: {status}")
            return 0
        ref = wa.upload_media(VIDEO)
        answer = wa.call_tool("create_meta_template", {
            "name": TEMPLATE_NAME, "body": TEMPLATE_BODY, "category": "UTILITY",
            "language": s.whatsapp_language, "header_type": "video",
            "header_media_url": ref})
        print(f"Sent to Meta for approval: {answer}")
        print("Check again with this script (no options) - it shows the status.")
        return 0

    engine = create_engine(s.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as db:
        ws = db.execute(select(Workspace).where(Workspace.slug == a.workspace)).scalar_one_or_none()
    if ws is None:
        print(f"No workspace {a.workspace!r}.")
        return 1

    with workspace(ws.id), Session(engine) as db:
        chosen, left_out = recipients(db)
        if a.only:
            wanted = {c.upper() for c in a.only}
            chosen = [c for c in chosen if c[0].csp_id.upper() in wanted]
        if a.limit:
            chosen = chosen[:a.limit]

        print(f"Will get the video: {len(chosen)} CSP(s) that have not received "
              f"their documents ({len({r.csp_id for r, _, _ in chosen})} different CSP codes)")
        for r, phone, at in chosen:
            link = f"link sent {at:%d %b}" if at else "no form link yet"
            print(f"  {r.csp_id}  {(r.name or '')[:30]:30}  {masked(phone)}  {link}")
        for label, n in breakdown(db, chosen):
            print(f"  {n:5}  {label}")
        if left_out:
            print("Left out:")
            for why, n in sorted(left_out.items()):
                print(f"  {n:5}  {why}")
        status = template_status()
        print(f"WhatsApp wording {TEMPLATE_NAME}: {status}")

        if not a.send:
            print("Nothing sent (add --send --by <your email> to send).")
            return 0
        if not a.by.strip():
            print("--by <your email> is required with --send.")
            return 1
        if s.test_copy:
            print("TEST_COPY: nothing is sent from the test copy.")
            return 1
        if not link_is_reachable(s.public_app_url):
            print("This copy is not on a public address - only the server sends.")
            return 1
        if status in ("PENDING", "REJECTED") or status.startswith("unknown"):
            print("Not sent: Meta has not approved the wording "
                  "(run --create-template once, then wait).")
            return 1
        if status == "NOT LISTED":
            print("The wording is not in the platform's list (it may stop at 100 "
                  "templates). Trying; stops at the first failure.")
        if not chosen:
            return 0

        ref = wa.upload_media(VIDEO)
        sent = failed = 0
        for i, (r, phone, _) in enumerate(chosen, 1):
            name = r.name or "CSP"
            body = TEMPLATE_BODY.replace("{{1}}", name)
            try:
                job = wa.call_tool("upload_contacts", {
                    "contacts": [{"phone": phone, "name": wa.one_line(name)}],
                    "source_name": message_log.source_name("guide_video", r.csp_id)})
                answer = wa.call_tool("send_template_message", {
                    "job_id": job.get("job_id"), "template_name": TEMPLATE_NAME,
                    "phone_column": "phone", "language": s.whatsapp_language,
                    "mapping": {"1": {"type": "column", "value": "name"}},
                    "header_type": "video", "header_media_url": ref})
                ok = int(answer.get("sent", 0) or 0) >= 1
                outcome = {"status": wa.SENT if ok else wa.FAILED,
                           "reason": "" if ok else f"not sent: {str(answer)[:300]}",
                           "job_id": job.get("job_id"), "template_name": TEMPLATE_NAME}
            except wa.WhatsAppPlatformError as e:
                ok, outcome = False, {"status": wa.FAILED, "reason": str(e)[:300],
                                      "job_id": None, "template_name": TEMPLATE_NAME}
            with send_reason.because(send_reason.GUIDE_VIDEO):
                message_log.record(db, kind=KIND_OTHER, mobile=phone, outcome=outcome,
                                   csp_id=r.csp_id, csp_name=r.name or "",
                                   body_text="[video] " + body, sent_by=a.by.strip())
            _audit(db, r, a.by.strip(), "whatsapp", "[video] " + body,
                   {"sent": ok, "kind": "guide_video", "reason": outcome["reason"]})
            db.commit()
            sent += ok
            failed += not ok
            print(f"  [{i}/{len(chosen)}] {r.csp_id} {'sent' if ok else 'FAILED: ' + outcome['reason']}")
            if i == 1 and not ok:
                print("Stopped: the first send failed, so the rest would too. "
                      "Fix the reason above and run again (nobody gets it twice).")
                break
            time.sleep(a.pause)
        print(f"Done: {sent} sent, {failed} failed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
