"""Send yourself the message a CSP with missing details gets, as a test — by
email, by WhatsApp, or both. By default the "these details are still needed"
message (--message missing); --message confirm sends "please confirm your
details" instead.

    python scripts/test_details_email.py --list
    python scripts/test_details_email.py <CSP code> --to you@eko.co.in
    python scripts/test_details_email.py <CSP code> --whatsapp 98XXXXXXXX

On the server (the link in the email only works there):

    docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \\
        exec -T api python scripts/test_details_email.py --list
    docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \\
        exec -T api python scripts/test_details_email.py 1A850534 --to you@eko.co.in
    ... exec -T api python scripts/test_details_email.py 1A850534 --whatsapp 98XXXXXXXX

Tracker No. 108. The exact email a CSP with missing details would get —
the stored wording, the list of what is missing, and a working link to their
form — sent to the address given with --to and/or the number given with
--whatsapp, NEVER to the CSP. The WhatsApp test goes through Eko's platform
with the same Meta-approved wording a CSP gets (No. 107/108). Real CSPs are
still asked on WhatsApp only (No. 53); nothing about that changes.

The link opens the real form for that CSP. Looking is harmless; SUBMITTING
it writes the values into the real sheet. The CSP's own request is not
blocked: the next real ask closes this test link and issues a fresh one.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import telemetry  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models.csp_record import CSPRecord  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services import data_request_service as drs  # noqa: E402
from app.services import field_ownership as fo  # noqa: E402
from app.services import message_sender  # noqa: E402
from app.workspace_context import workspace  # noqa: E402

EKO = "sbi-kiosk-csp"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csp_code", nargs="?")
    ap.add_argument("--to", help="email address for the test (never the CSP)")
    ap.add_argument("--whatsapp", help="mobile number for a WhatsApp test "
                    "(never the CSP)")
    ap.add_argument("--message", choices=("missing", "confirm"), default="missing",
                    help="missing = 'these details are still needed: …' "
                         "(default); confirm = 'please confirm your details'")
    ap.add_argument("--list", action="store_true",
                    help="show CSPs with missing details, send nothing")
    ap.add_argument("--workspace", default=EKO, help="workspace slug (default: Eko)")
    a = ap.parse_args()
    telemetry.setup("cspdocmaker-script", "WARNING")

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as db:
        ws = db.execute(select(Workspace).where(
            Workspace.slug == a.workspace)).scalar_one_or_none()
    if ws is None:
        print(f"No workspace {a.workspace!r}.")
        return 1

    with workspace(ws.id), Session(engine) as db:
        if a.list or not a.csp_code:
            shown = 0
            for c in db.execute(select(CSPRecord).order_by(CSPRecord.csp_id)).scalars():
                missing = drs.fields_to_ask(c)
                if missing:
                    print(f"  {c.csp_id}  {c.name or ''}  — missing: "
                          f"{', '.join(fo.label_of(f) for f in missing)}")
                    shown += 1
            print(f"{shown} CSP(s) with missing details." if shown
                  else "No CSP has missing details.")
            return 0

        from app.services import whatsapp_platform as wa
        if not a.to and not a.whatsapp:
            print("Say where to send the test: --to you@eko.co.in and/or "
                  "--whatsapp 98XXXXXXXX (never the CSP).")
            return 1
        if a.to and not EMAIL.match(a.to):
            print(f"{a.to!r} is not an email address.")
            return 1
        if a.whatsapp and not wa.phone_for_whatsapp(a.whatsapp):
            print(f"{a.whatsapp!r} is not a usable mobile number "
                  f"(10 digits, or 91 + 10 digits).")
            return 1

        record = db.execute(select(CSPRecord).where(
            (CSPRecord.csp_id == a.csp_code) | (CSPRecord.csp_code == a.csp_code)
        )).scalars().first()
        if record is None:
            print(f"No CSP {a.csp_code} (has the sheet been read yet?).")
            return 1
        fields = drs.fields_to_ask(record)
        if not fields:
            print(f"{record.csp_id} has nothing missing — the real email would "
                  f"not be sent. Pick one from --list.")
            return 1

        try:
            from app.models.messaging import (
                PURPOSE_DATA_REQUEST, PURPOSE_MISSING_DATA)
            template = message_sender.choose_template(
                db, PURPOSE_MISSING_DATA if a.message == "missing"
                else PURPOSE_DATA_REQUEST)
        except message_sender.NoTemplate as e:
            print(f"Not sent: {e}")
            return 1
        request, token = drs.create(db, record.csp_id, fo.request_fields(record))
        link = drs.link_for(token)
        if not message_sender.link_is_reachable(link):
            db.rollback()
            print("Not sent: " + message_sender.why_unreachable(link)
                  + " Run this on the server.")
            return 1

        name = record.name or record.csp_id
        # Kept as plain values: after the commit below the record can no
        # longer be read once the session closes (DetachedInstanceError).
        csp_id, csp_name = record.csp_id, record.name or ""
        results = []

        if a.to:
            body = message_sender.render(template.body, name=name, link=link,
                                         fields=fields)
            subject = "[TEST] " + (template.subject or (
                "Details still needed for your CSP documents"
                if a.message == "missing" else "Please confirm your details"))
            # Straight through the server's email account (the one that
            # emails CSPs their documents): no Email messaging channel is
            # needed, and none is on — real CSPs are asked on WhatsApp only.
            sent, why = message_sender._send_email(a.to, subject, body)
            results.append(("email", a.to, sent, why, None))

        if a.whatsapp:
            # Exactly what ask_for_details sends a CSP: the stored wording as
            # a Meta template, the same values — to the test number only.
            outcome = wa.send(
                a.whatsapp, template.body,
                {"name": name, "link": link,
                 "fields": ", ".join(fo.label_of(f) for f in fields)},
                source_name=f"CSPdocMaker TEST details request {record.csp_id}")
            results.append(("WhatsApp", a.whatsapp, outcome["status"] == wa.SENT,
                            (f"{outcome['status']}: {outcome['reason']}"
                             if outcome["status"] != wa.SENT else ""),
                            outcome.get("job_id")))

        if not any(r[2] for r in results):
            db.rollback()       # nothing went out: no test link left behind
        else:
            # Deliberately NOT recorded as "asked": sent_to stays empty, so
            # the CSP's real ask still goes out (and closes this test link).
            request.sent_via = "test"
            db.commit()

    print(f"Test of the '{a.message}' message for {csp_id} ({csp_name}) — "
          f"missing: {', '.join(fo.label_of(f) for f in fields)}")
    for via, to, sent, why, job_id in results:
        if sent:
            print(f"  {via}: SENT to {to}" + (f"  (job {job_id})" if job_id else ""))
        else:
            print(f"  {via}: NOT sent to {to} — {why}")
    if any(r[0] == "WhatsApp" and r[2] for r in results):
        print("  Delivered / read? python scripts/check_whatsapp.py --status <job>")
    if any(r[2] for r in results):
        print("The link opens the real form: look freely, but submitting it "
              "writes to the real sheet.")
    return 0 if all(r[2] for r in results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:      # a plain reason, not a traceback
        print(f"NOT sent: {type(e).__name__}: {e}")
        sys.exit(1)
