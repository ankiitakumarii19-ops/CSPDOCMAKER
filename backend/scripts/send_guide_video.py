"""Send the "how to fill the details form" video on WhatsApp (No. 209).

To: KOs (8-character code) who were sent a details-form link, have not
submitted the form, and have not had their documents emailed. Never a CSP on
hold, never one without a usable mobile, never twice (a CSP who already got
this video is skipped on every later run).

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
from app.models.data_request import ANSWERED, DataRequest  # noqa: E402
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
KO_LENGTH = 8


def masked(phone: str) -> str:
    return phone[:4] + "*" * max(len(phone) - 6, 0) + phone[-2:]


def recipients(db):
    """(record, phone, link_sent_at) for everyone who should get the video,
    plus {reason: count} for everyone left out."""
    from app.services import csp_replies, send_reason
    from app.services import whatsapp_platform as wa

    asked = dict(db.execute(
        select(DataRequest.csp_id, func.max(DataRequest.created_at))
        .where(DataRequest.sent_via.is_not(None))
        .group_by(DataRequest.csp_id)).all())
    answered = set(db.execute(select(DataRequest.csp_id).where(
        DataRequest.status == ANSWERED)).scalars())
    already = set(db.execute(select(WhatsAppMessage.csp_id).where(
        WhatsAppMessage.sent_because == send_reason.GUIDE_VIDEO,
        WhatsAppMessage.send_status == "sent")).scalars())

    chosen, left_out = [], {}

    def skip(why):
        left_out[why] = left_out.get(why, 0) + 1

    for r in db.execute(select(CSPRecord).order_by(CSPRecord.csp_id)).scalars():
        code = (r.csp_id or "").strip()
        if code not in asked:
            continue                      # never sent a form link: not counted
        if len(code) != KO_LENGTH:
            skip("Sub-KO (not a KO)")
        elif code in answered:
            skip("already submitted the form")
        elif (r.send_hold or "").strip():
            skip("on hold")
        elif csp_replies._documents_emailed(db, code) is not None:
            skip("documents already emailed")
        elif code in already:
            skip("already got this video")
        elif not wa.phone_for_whatsapp(r.mobile or ""):
            skip("no usable mobile number")
        else:
            chosen.append((r, wa.phone_for_whatsapp(r.mobile), asked[code]))
    return chosen, left_out


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

        print(f"Will get the video: {len(chosen)} KO(s)")
        for r, phone, at in chosen:
            print(f"  {r.csp_id}  {(r.name or '')[:30]:30}  {masked(phone)}  link sent {at:%d %b}")
        if left_out:
            print("Left out (got a form link but):")
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
