"""Check that WhatsApp sending works, and optionally send a test message.

Run from the backend directory:

    .venv/Scripts/python.exe scripts/check_whatsapp.py
    .venv/Scripts/python.exe scripts/check_whatsapp.py --send 98XXXXXXXX
    .venv/Scripts/python.exe scripts/check_whatsapp.py --status <job id>

Without --send it only proves Eko's WhatsApp platform answers and offers the
tools this app uses. Nothing is sent.

With --send it delivers a real test message to that number. The very first
time, Meta has to approve the test wording (minutes to about a day): the
answer is then "waiting for approval" and nothing is sent. Run the same
command again later and it is sent.

With --status it asks Meta whether a past send was delivered / read.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import telemetry  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services import whatsapp_platform as wa  # noqa: E402

settings = get_settings()

OK = "  OK   "
BAD = " FAIL  "
WARN = " WARN  "
NEEDED_TOOLS = ("upload_contacts", "smart_send_template", "get_delivery_status")

# Kept fixed on purpose: Meta approves a wording once, and later tests reuse
# that approval as long as the text does not change.
TEST_BODY = ("Namaste {name}, this is a test message from CSPdocMaker to check "
             "that WhatsApp delivery works. No action is needed.")


def report(status, message):
    print(f"[{status}] {message}")


def masked(phone: str) -> str:
    return phone[:4] + "*" * max(len(phone) - 6, 0) + phone[-2:]


def check_platform() -> bool:
    print("=== Eko WhatsApp platform ===")
    report(OK, f"address: {settings.whatsapp_platform_url}")
    try:
        result = wa._rpc("tools/list", {})
    except wa.WhatsAppPlatformError as e:
        report(BAD, str(e))
        print("       Check this machine can reach the address above "
              "(VPN / office network if it is internal).")
        return False
    names = {t.get("name") for t in result.get("tools", []) if isinstance(t, dict)}
    missing = [n for n in NEEDED_TOOLS if n not in names]
    if missing:
        report(BAD, f"the platform answered but lacks: {', '.join(missing)}")
        return False
    report(OK, f"platform answered; offers {len(names)} tools including "
               f"{', '.join(NEEDED_TOOLS)}")
    return True


def send_test(mobile: str) -> bool:
    phone = wa.phone_for_whatsapp(mobile)
    if not phone:
        report(BAD, "not a usable Indian mobile number (10 digits, or 91 + 10 digits)")
        return False
    print(f"\n=== sending a test message to {masked(phone)} ===")
    outcome = wa.send(phone, TEST_BODY, {"name": "Tester"},
                      source_name="CSPdocMaker WhatsApp test")
    status, reason = outcome["status"], outcome["reason"]
    if outcome.get("job_id"):
        print(f"       job id: {outcome['job_id']}   template: {outcome.get('template_name')}")
    if status == wa.SENT:
        report(OK, "the platform sent it — check the phone")
        print("       To see whether it was delivered / read:")
        print(f"         .venv/Scripts/python.exe scripts/check_whatsapp.py --status {outcome['job_id']}")
        return True
    if status == wa.PENDING:
        report(WARN, reason)
        print("       Nothing was sent yet. Run the same --send command again once "
              "Meta has approved the wording.")
        return True
    report(BAD, f"{status}: {reason}")
    return False


def show_status(job_id: str) -> bool:
    print(f"=== delivery status for job {job_id} ===")
    try:
        answer = wa.delivery_status(job_id)
    except wa.WhatsAppPlatformError as e:
        report(BAD, str(e))
        return False
    for key, value in answer.items():
        print(f"       {key}: {value}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", metavar="MOBILE",
                        help="also send a real test message to this number")
    parser.add_argument("--status", metavar="JOB_ID",
                        help="show delivered / read for a past send")
    args = parser.parse_args()

    telemetry.setup("cspdocmaker-script", "WARNING")
    with telemetry.run(name="check_whatsapp") as run_id:
        if args.status:
            ok = show_status(args.status)
        else:
            ok = check_platform()
            if ok and args.send:
                ok = send_test(args.send)
            elif ok:
                print("\nThe platform is reachable. Send a real test with:")
                print("  .venv/Scripts/python.exe scripts/check_whatsapp.py --send 98XXXXXXXX")
    if not ok:
        print(f"\nDetails: .venv/Scripts/python.exe scripts/show_run.py {run_id}")
    raise SystemExit(0 if ok else 1)


main()
