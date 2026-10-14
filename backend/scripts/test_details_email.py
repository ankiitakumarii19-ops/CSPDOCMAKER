"""Send yourself the CSP's "please confirm your details" email, as a test.

    python scripts/test_details_email.py --list
    python scripts/test_details_email.py <CSP code> --to you@eko.co.in

On the server (the link in the email only works there):

    docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \\
        exec -T api python scripts/test_details_email.py --list
    docker compose -f docker-compose.prod.yml --env-file deploy/.env.production \\
        exec -T api python scripts/test_details_email.py 1A850534 --to you@eko.co.in

Tracker No. 108. The exact email a CSP with missing details would get —
the stored wording, the list of what is missing, and a working link to their
form — sent to the address given with --to, NEVER to the CSP. Real CSPs are
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
    ap.add_argument("--to", help="where to send the test (never the CSP)")
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

        if not a.to or not EMAIL.match(a.to):
            print("Give the test address with --to you@eko.co.in "
                  "(it is never sent to the CSP).")
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

        template = message_sender.choose_template(db)
        request, token = drs.create(db, record.csp_id, fo.request_fields(record))
        link = drs.link_for(token)
        if not message_sender.link_is_reachable(link):
            db.rollback()
            print("Not sent: " + message_sender.why_unreachable(link)
                  + " Run this on the server.")
            return 1

        body = message_sender.render(
            template.body, name=record.name or record.csp_id,
            link=link, fields=fields)
        subject = "[TEST] " + (template.subject or "Please confirm your details")
        sent, why = message_sender.send_via(
            message_sender.choose_channel(db, "email"), a.to, subject, body)

        # Deliberately NOT recorded as "asked": sent_to stays empty, so the
        # CSP's real ask still goes out (and closes this test link).
        request.sent_via = "email-test"
        request.delivery_error = None if sent else why
        db.commit()

    if not sent:
        print(f"NOT sent: {why}")
        return 1
    print(f"Sent the details-request email for {record.csp_id} "
          f"({record.name}) to {a.to}.")
    print(f"Missing: {', '.join(fo.label_of(f) for f in fields)}")
    print("The link opens the real form: look freely, but submitting it writes "
          "to the real sheet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
