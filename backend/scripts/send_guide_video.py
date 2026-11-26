"""Send the "how to fill the details form" video on WhatsApp (No. 209, 254).

To: every CSP that has not yet RECEIVED its documents by email (No. 254-255)
- KO or Sub-KO, sent a form link or not, form filled or not. One send per CSP
code: the code is the unique key, so a code seen twice is sent to once.

Try it first (No. 258): --test-to <your mobile> sends the video to that one
number only - no CSP, nothing recorded against a CSP - and says how long the
upload and the send took.

With the video goes the CSP's verification link (No. 256): right after the
video, the usual details-form WhatsApp with a NEW link (the same as the
"Details form" button on Messaging - the earlier link closes once the new
one arrives). The link goes only after the video went. A CSP whose video
went but whose link did not is sent only the link on the next run. Never a CSP that was in CSPDATA
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
import logging
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
    hold, one without a usable number, or one that already got the video
    and its link.

    Each chosen row is (record, phone, last link sent or None, needs_video):
    needs_video False = the video went earlier but no link after it."""
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
    # When each CSP got the video; a link sent at or after that went with it.
    video_at = dict(db.execute(
        select(WhatsAppMessage.csp_id, func.max(WhatsAppMessage.sent_at)).where(
            WhatsAppMessage.sent_because == send_reason.GUIDE_VIDEO,
            WhatsAppMessage.send_status == "sent")
        .group_by(WhatsAppMessage.csp_id)).all())
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
        elif (r.csp_id in video_at and asked.get(r.csp_id) is not None
              and asked[r.csp_id] >= video_at[r.csp_id]):
            skip("already got the video and its link")
        elif not wa.phone_for_whatsapp(r.mobile or ""):
            skip("no usable mobile number")
        else:
            seen.add(key)
            chosen.append((r, wa.phone_for_whatsapp(r.mobile), asked.get(r.csp_id),
                           r.csp_id not in video_at))
    return chosen, left_out


def breakdown(db, chosen):
    """Who the chosen are, as (label, count) lines for the dry run."""
    filled = set(db.execute(select(DataRequest.csp_id).where(
        DataRequest.status == "answered")).scalars())
    rows = [(r, at) for r, _, at, _ in chosen]
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
        ("got the video earlier - only the link is left",
         sum(1 for *_, needs_video in chosen if not needs_video)),
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


def _platform_send(wa, phone, name, ref, source_name, s):
    """The video wording with the video to one number; the outcome dict."""
    try:
        job = wa.call_tool("upload_contacts", {
            "contacts": [{"phone": phone, "name": wa.one_line(name)}],
            "source_name": source_name})
        answer = wa.call_tool("send_template_message", {
            "job_id": job.get("job_id"), "template_name": TEMPLATE_NAME,
            "phone_column": "phone", "language": s.whatsapp_language,
            "mapping": {"1": {"type": "column", "value": "name"}},
            "header_type": "video", "header_media_url": ref})
        ok = int(answer.get("sent", 0) or 0) >= 1
        return {"status": wa.SENT if ok else wa.FAILED,
                "reason": "" if ok else f"not sent: {str(answer)[:300]}",
                "job_id": job.get("job_id"), "template_name": TEMPLATE_NAME}
    except wa.WhatsAppPlatformError as e:
        return {"status": wa.FAILED, "reason": str(e)[:300],
                "job_id": None, "template_name": TEMPLATE_NAME}


def _send_video(db, wa, r, phone, ref, body, by, message_log, send_reason,
                _audit, s):
    """The video to one CSP, logged; (sent?, reason)."""
    outcome = _platform_send(wa, phone, r.name or "CSP", ref,
                             message_log.source_name("guide_video", r.csp_id), s)
    ok = outcome["status"] == wa.SENT
    with send_reason.because(send_reason.GUIDE_VIDEO):
        message_log.record(db, kind=KIND_OTHER, mobile=phone, outcome=outcome,
                           csp_id=r.csp_id, csp_name=r.name or "",
                           body_text="[video] " + body, sent_by=by)
    _audit(db, r, by, "whatsapp", "[video] " + body,
           {"sent": ok, "kind": "guide_video", "reason": outcome["reason"]})
    db.commit()
    return ok, outcome["reason"]


def _send_link(db, r, channel, by, message_sender, send_reason, _audit):
    """The usual verification-link WhatsApp with a NEW link to one CSP, the
    same as the Details form button (No. 192); (sent?, reason)."""
    try:
        with send_reason.because(send_reason.GUIDE_VIDEO_LINK), \
                send_reason.sent_by(by):
            outcome = message_sender.ask_for_details(
                db, r, channel=channel, manual=True, verify=True, fresh=True)
        ok, why = bool(outcome.get("sent")), outcome.get("reason") or ""
    except Exception as e:  # one CSP's failure must not stop the others
        db.rollback()
        logging.getLogger(__name__).exception(
            "send_guide_video: the verification link to %s failed", r.csp_id)
        ok, why = False, f"{type(e).__name__}: {e}"[:300]
    _audit(db, r, by, "whatsapp", "Verification link (with the form video)",
           {"sent": ok, "kind": "guide_video_link", "reason": why})
    db.commit()
    return ok, why


def _try_on_one_number(mobile, s, wa, link_is_reachable) -> int:
    """No. 258: the video to one number, timed. Nothing recorded per CSP."""
    phone = wa.phone_for_whatsapp(mobile)
    if not phone:
        print(f"Not a usable mobile number: {mobile!r} (10 digits, or 91 + 10).")
        return 1
    if s.test_copy:
        print("TEST_COPY: nothing is sent from the test copy.")
        return 1
    if not link_is_reachable(s.public_app_url):
        print("This copy is not on a public address - only the server sends.")
        return 1
    status = template_status()
    print(f"WhatsApp wording {TEMPLATE_NAME}: {status}")
    if status in ("PENDING", "REJECTED") or status.startswith("unknown"):
        print("Not sent: Meta has not approved the wording "
              "(run --create-template once, then wait).")
        return 1
    size = os.path.getsize(VIDEO) / 1024 / 1024
    start = time.monotonic()
    try:
        ref = wa.upload_media(VIDEO)
    except wa.WhatsAppPlatformError as e:
        print(f"FAILED: the platform did not take the video ({size:.1f} MB): {e}")
        return 1
    uploaded = time.monotonic()
    print(f"Video ({size:.1f} MB) given to the platform in {uploaded - start:.1f} s.")
    outcome = _platform_send(wa, phone, "Test", ref, "guide_video_test", s)
    done = time.monotonic()
    if outcome["status"] != wa.SENT:
        print(f"FAILED after {done - uploaded:.1f} s: {outcome['reason']}")
        return 1
    print(f"Sent to {masked(phone)} in {done - uploaded:.1f} s "
          f"(total {done - start:.1f} s, job {outcome['job_id']}).")
    print("Check the phone: the video should arrive with the message. In a real "
          "run the video is given to the platform once, then each CSP takes "
          "about the send time above plus their verification link and the "
          "pause (--pause, 1 s).")
    return 0


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
    ap.add_argument("--test-to", default="",
                    help="send the video to this one mobile only (a try; no CSP)")
    a = ap.parse_args()
    telemetry.setup("cspdocmaker-script", "WARNING")

    from app.services import message_log, send_reason
    from app.services import whatsapp_platform as wa
    from app.services.manual_messages import _audit
    from app.services import message_sender
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

    if a.test_to:
        return _try_on_one_number(a.test_to, s, wa, link_is_reachable)

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
              f"their documents ({len({r.csp_id for r, *_ in chosen})} different CSP codes)")
        print("Each gets the video, then their verification link (a new one).")
        for r, phone, at, _ in chosen:
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

        try:
            link_channel = message_sender.choose_channel(db, kind="whatsapp")
        except message_sender.NoChannel as e:
            print(f"Not sent: no WhatsApp channel for the verification link ({e}).")
            return 1
        ref = wa.upload_media(VIDEO)
        sent = failed = links = link_failed = 0
        run_start = time.monotonic()
        for i, (r, phone, _, needs_video) in enumerate(chosen, 1):
            one_start = time.monotonic()
            body = TEMPLATE_BODY.replace("{{1}}", r.name or "CSP")
            if needs_video:
                ok, why = _send_video(db, wa, r, phone, ref, body, a.by.strip(),
                                      message_log, send_reason, _audit, s)
                sent += ok
                failed += not ok
                if not ok:
                    print(f"  [{i}/{len(chosen)}] {r.csp_id} video FAILED: {why}")
                    if i == 1:
                        print("Stopped: the first send failed, so the rest would too. "
                              "Fix the reason above and run again (nobody gets it twice).")
                        break
                    time.sleep(a.pause)
                    continue          # no link without the video; next run tries both
            link_ok, link_why = _send_link(db, r, link_channel, a.by.strip(),
                                           message_sender, send_reason, _audit)
            links += link_ok
            link_failed += not link_ok
            print(f"  [{i}/{len(chosen)}] {r.csp_id} "
                  f"{'video sent, ' if needs_video else 'video sent earlier, '}"
                  f"{'link sent' if link_ok else 'link FAILED: ' + link_why}"
                  f" ({time.monotonic() - one_start:.1f} s)")
            time.sleep(a.pause)
        print(f"Done in {time.monotonic() - run_start:.0f} s: videos {sent} sent, "
              f"{failed} failed; links {links} sent, {link_failed} failed.")
        if failed or link_failed:
            print("Run again later: anyone who missed the video or the link "
                  "gets what they missed (nobody gets the video twice).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
