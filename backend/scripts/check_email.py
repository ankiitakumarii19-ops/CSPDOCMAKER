"""Check that outgoing email is configured, and optionally send a test.

Run from the backend directory:

    .venv/Scripts/python.exe scripts/check_email.py
    .venv/Scripts/python.exe scripts/check_email.py --send you@eko.co.in

Without --send it only inspects the configuration and proves the SMTP server
accepts the credentials. With --send it delivers a real message.

It never prints the password, only whether one is set and how long it is.
"""

import argparse
import os
import smtplib
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402

settings = get_settings()

OK = "  OK   "
BAD = " FAIL  "
WARN = " WARN  "


def report(status, message):
    print(f"[{status}] {message}")


def check_configuration() -> bool:
    print("=== configuration ===")
    ok = True

    method = settings.email_method.lower().strip()
    if method == "console":
        report(WARN, "EMAIL_METHOD=console — mail is printed to the log, "
                     "never delivered. Set EMAIL_METHOD=smtp to send for real.")
        return False
    if method not in ("smtp", "gmail_api"):
        report(BAD, f"EMAIL_METHOD={method!r} is not one of: smtp, gmail_api, console")
        return False
    report(OK, f"EMAIL_METHOD={method}")

    if method == "gmail_api":
        report(WARN, "gmail_api selected — this script only checks SMTP.")
        return False

    if not settings.smtp_host:
        report(BAD, "SMTP_HOST is empty")
        ok = False
    else:
        report(OK, f"SMTP_HOST={settings.smtp_host}:{settings.smtp_port}")

    if not settings.smtp_username:
        report(BAD, "SMTP_USERNAME is empty")
        ok = False
    else:
        report(OK, f"SMTP_USERNAME={settings.smtp_username}")

    password = settings.smtp_password
    if not password:
        report(BAD, "SMTP_PASSWORD is empty")
        ok = False
    elif " " in password:
        report(BAD, f"SMTP_PASSWORD contains spaces ({len(password)} chars). "
                    "A Gmail App Password is shown as 'abcd efgh ijkl mnop' but "
                    "must be stored WITHOUT the spaces.")
        ok = False
    elif settings.smtp_host == "smtp.gmail.com" and len(password) != 16:
        report(WARN, f"SMTP_PASSWORD is {len(password)} characters. A Gmail App "
                     "Password is exactly 16. A normal account password will "
                     "not work.")
    else:
        report(OK, f"SMTP_PASSWORD is set ({len(password)} characters)")

    sender = settings.smtp_from_email or settings.smtp_username
    if not sender:
        report(BAD, "SMTP_FROM_EMAIL and SMTP_USERNAME are both empty")
        ok = False
    else:
        report(OK, f"sending as {settings.smtp_from_name} <{sender}>")

    return ok


def check_connection() -> bool:
    print("\n=== connection ===")
    try:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
    except socket.timeout:
        report(BAD, f"timed out connecting to {settings.smtp_host}:{settings.smtp_port}. "
                    "A firewall or the network may be blocking outbound SMTP.")
        return False
    except OSError as e:
        report(BAD, f"could not reach {settings.smtp_host}:{settings.smtp_port}: {e}")
        return False

    report(OK, f"connected to {settings.smtp_host}:{settings.smtp_port}")

    try:
        server.ehlo()
        if settings.smtp_use_tls:
            server.starttls()
            server.ehlo()
            report(OK, "STARTTLS negotiated")

        server.login(settings.smtp_username, settings.smtp_password)
        report(OK, "authentication accepted")
        return True

    except smtplib.SMTPAuthenticationError as e:
        code = getattr(e, "smtp_code", "?")
        report(BAD, f"authentication rejected (SMTP {code}).")
        print("\n       For Gmail this almost always means one of:")
        print("         * the password is a normal account password, not an App Password")
        print("         * 2-Step Verification is off, so App Passwords cannot exist")
        print("         * your Workspace admin has disabled App Passwords")
        print("         * the App Password was revoked")
        return False
    except smtplib.SMTPException as e:
        report(BAD, f"SMTP error: {type(e).__name__}: {e}")
        return False
    finally:
        try:
            server.quit()
        except Exception:
            pass


def send_test(recipient: str) -> bool:
    from app.services import email_service

    print(f"\n=== sending a test message to {recipient} ===")
    sent = email_service.send_otp_email(
        to_email=recipient, otp_code="000000", user_name="Configuration Test",
    )
    if sent:
        report(OK, f"message accepted by the server for {recipient}")
        print("       Check the inbox, and the spam folder. The code in it is "
              "a fixed 000000 and is not a real OTP.")
    else:
        report(BAD, "the mailer refused to send — see the errors logged above")
    return sent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", metavar="EMAIL",
                        help="also deliver a real test message to this address")
    args = parser.parse_args()

    configured = check_configuration()
    if not configured:
        print("\nFix the items marked FAIL in backend/.env, then run this again.")
        raise SystemExit(1)

    if not check_connection():
        raise SystemExit(1)

    if args.send:
        raise SystemExit(0 if send_test(args.send) else 1)

    print("\nConfiguration looks good. Deliver a real test with:")
    print("  .venv/Scripts/python.exe scripts/check_email.py --send you@eko.co.in")


main()
