"""
CSP DocMaker — Email Service

Sends OTP emails via SMTP or Gmail API.

Supported modes (configured via EMAIL_METHOD env var):
  - 'smtp'      : Standard SMTP (Gmail App Password, company SMTP, etc.)
  - 'gmail_api' : Google Gmail API with service account + domain-wide delegation
  - 'console'   : Logs email to console only (development fallback)
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, List

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


def _build_otp_html(otp_code: str, user_name: Optional[str] = None) -> str:
    """Build a professional HTML email body for OTP delivery."""
    greeting = f"Hi {user_name}," if user_name else "Hi,"
    return f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f7;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.06);overflow:hidden;">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#6366f1,#06b6d4);padding:32px 32px 24px;text-align:center;">
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;">
                CSP DocMaker
              </h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">
                Document Generation &amp; Email Automation
              </p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px;color:#374151;font-size:15px;line-height:1.6;">
                {greeting}
              </p>
              <p style="margin:0 0 24px;color:#374151;font-size:15px;line-height:1.6;">
                Your one-time password (OTP) for CSP DocMaker is:
              </p>
              <div style="text-align:center;margin:0 0 24px;">
                <div style="display:inline-block;background:#f0f1ff;border:2px solid #6366f1;border-radius:10px;padding:16px 36px;letter-spacing:0.4em;font-size:32px;font-weight:700;color:#4338ca;font-family:'Courier New',monospace;">
                  {otp_code}
                </div>
              </div>
              <p style="margin:0 0 8px;color:#6b7280;font-size:13px;line-height:1.5;">
                This code expires in <strong>5 minutes</strong>. Do not share it with anyone.
              </p>
              <p style="margin:0;color:#6b7280;font-size:13px;line-height:1.5;">
                If you did not request this code, please ignore this email.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:20px 32px;background:#f9fafb;border-top:1px solid #e5e7eb;text-align:center;">
              <p style="margin:0;color:#9ca3af;font-size:11px;">
                This is an automated message from CSP DocMaker — Internal EKO Platform.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _console_allowed() -> bool:
    """Console delivery prints messages instead of sending them. It is a
    development convenience only and must never silently 'succeed' elsewhere."""
    if settings.app_env == "development":
        return True
    logger.error(
        "email_service: EMAIL_METHOD=console is only allowed when APP_ENV=development "
        "(current APP_ENV=%s). Refusing to report a fake successful delivery.",
        settings.app_env,
    )
    return False


def _build_otp_plain(otp_code: str, user_name: Optional[str] = None) -> str:
    """Build a plain-text fallback for the OTP email."""
    greeting = f"Hi {user_name}," if user_name else "Hi,"
    return (
        f"{greeting}\n\n"
        f"Your OTP for CSP DocMaker is: {otp_code}\n\n"
        f"This code expires in 5 minutes. Do not share it with anyone.\n"
        f"If you did not request this code, please ignore this email.\n\n"
        f"— CSP DocMaker (Internal EKO Platform)"
    )


def _send_via_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str,
) -> bool:
    """Send an email via SMTP."""
    from_email = settings.smtp_from_email or settings.smtp_username
    if not from_email:
        logger.error(
            "email_service._send_via_smtp: SMTP_FROM_EMAIL and SMTP_USERNAME are both empty. "
            "Configure at least one in .env."
        )
        return False

    if not settings.smtp_username or not settings.smtp_password:
        logger.error(
            "email_service._send_via_smtp: SMTP_USERNAME or SMTP_PASSWORD not configured in .env."
        )
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.smtp_from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # Attach plain text first, then HTML (email clients prefer the last alternative)
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    from app import telemetry

    try:
        # Traced and classified (timeout / connection / auth); the handlers
        # below still decide what the caller is told.
        with telemetry.external_call("smtp", "send_message",
                                     attachments=len(msg.get_payload()) - 1):
            if settings.smtp_use_tls:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)

            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
            server.quit()

        logger.info("email_service._send_via_smtp: email sent to %s", to_email)
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(
            "email_service._send_via_smtp: SMTP authentication failed — "
            "check SMTP_USERNAME and SMTP_PASSWORD in .env: %s",
            e,
        )
        return False
    except smtplib.SMTPException as e:
        logger.error(
            "email_service._send_via_smtp: SMTP error sending to %s: %s: %s",
            to_email, type(e).__name__, e,
        )
        return False
    except Exception as e:
        logger.error(
            "email_service._send_via_smtp: unexpected error sending to %s: %s: %s",
            to_email, type(e).__name__, e,
        )
        return False


def _send_via_gmail_api(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: str,
) -> bool:
    """Send an email via Gmail API with service account + domain-wide delegation.

    Prerequisites:
    1. Gmail API enabled in Google Cloud Console
    2. Domain-wide delegation configured in Google Workspace Admin
    3. Service account authorized with scope: https://www.googleapis.com/auth/gmail.send
    4. GMAIL_CREDENTIALS_FILE and GMAIL_SENDER_EMAIL configured in .env
    """
    try:
        import base64
        from google.oauth2 import service_account as sa
        from googleapiclient.discovery import build

        credentials = sa.Credentials.from_service_account_file(
            settings.gmail_credentials_file,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        # Impersonate the sender email (requires domain-wide delegation)
        delegated_creds = credentials.with_subject(settings.gmail_sender_email)

        service = build("gmail", "v1", credentials=delegated_creds)

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{settings.smtp_from_name} <{settings.gmail_sender_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me",
            body={"raw": raw_message},
        ).execute()

        logger.info("email_service._send_via_gmail_api: email sent to %s", to_email)
        return True

    except FileNotFoundError:
        logger.error(
            "email_service._send_via_gmail_api: credentials file not found: %s. "
            "Switch to EMAIL_METHOD=smtp or create the credentials file.",
            settings.gmail_credentials_file,
        )
        return False
    except Exception as e:
        logger.error(
            "email_service._send_via_gmail_api: failed to send to %s: %s: %s",
            to_email, type(e).__name__, e,
        )
        return False


def send_otp_email(
    to_email: str,
    otp_code: str,
    user_name: Optional[str] = None,
    subject: Optional[str] = None,
) -> bool:
    """Send an OTP email using the configured delivery method.

    Args:
        to_email: Recipient email address.
        otp_code: The OTP code to include in the email.
        user_name: Optional user name for personalized greeting.
        subject: Overrides the default line, so a password-reset code can
            say what it is for. It must never contain the code itself.

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    # The OTP is never placed in the subject (visible in inbox previews and
    # mail-server logs) and never written to application logs.
    subject = subject or "CSP DocMaker — Your one-time password"
    html_body = _build_otp_html(otp_code, user_name)
    plain_body = _build_otp_plain(otp_code, user_name)

    method = settings.email_method.lower().strip()

    if method == "console":
        if not _console_allowed():
            return False
        # Console mode IS the delivery channel in local development: the OTP
        # goes to the developer's terminal only, never to the log handlers.
        print(f"\n{'='*50}")
        print(f"[CONSOLE EMAIL] To: {to_email}")
        print(f"[CONSOLE EMAIL] OTP: {otp_code}")
        print(f"{'='*50}\n")
        return True

    elif method == "gmail_api":
        return _send_via_gmail_api(to_email, subject, html_body, plain_body)

    elif method == "smtp":
        return _send_via_smtp(to_email, subject, html_body, plain_body)

    else:
        logger.error(
            "email_service.send_otp_email: unknown EMAIL_METHOD '%s'. "
            "Valid options: 'smtp', 'gmail_api', 'console'.",
            method,
        )
        return False


def _build_documents_html(csp_name: str, csp_id: str, doc_names: List[str]) -> str:
    """Build a professional HTML email for document delivery."""
    doc_list = "".join(f"<li style='margin:4px 0;'>{name}</li>" for name in doc_names)
    return f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f7;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.06);overflow:hidden;">
          <tr>
            <td style="background:linear-gradient(135deg,#6366f1,#06b6d4);padding:32px 32px 24px;text-align:center;">
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;">CSP DocMaker</h1>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">Document Delivery</p>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <p style="margin:0 0 16px;color:#374151;font-size:15px;">Dear {csp_name},</p>
              <p style="margin:0 0 16px;color:#374151;font-size:15px;">
                Please find attached your documents from EKO India Financial Services:
              </p>
              <div style="background:#f0f1ff;border:1px solid #e0e1ef;border-radius:8px;padding:16px;margin:0 0 20px;">
                <p style="margin:0 0 8px;font-weight:600;color:#4338ca;font-size:13px;">CSP ID: {csp_id}</p>
                <ul style="margin:0;padding-left:20px;color:#374151;font-size:14px;">
                  {doc_list}
                </ul>
              </div>
              <p style="margin:0;color:#6b7280;font-size:13px;">
                If you have any questions, please contact your Relationship Manager.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background:#f9fafb;border-top:1px solid #e5e7eb;text-align:center;">
              <p style="margin:0;color:#9ca3af;font-size:11px;">
                This is an automated message from CSP DocMaker — EKO India Financial Services.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_documents_plain(csp_name: str, csp_id: str, doc_names: List[str]) -> str:
    """Build a plain-text email for document delivery."""
    doc_list = "\n".join(f"  - {name}" for name in doc_names)
    return (
        f"Dear {csp_name},\n\n"
        f"Please find attached your documents from EKO India Financial Services.\n\n"
        f"CSP ID: {csp_id}\n\n"
        f"Documents:\n{doc_list}\n\n"
        f"If you have any questions, please contact your Relationship Manager.\n\n"
        f"— CSP DocMaker (EKO India Financial Services)"
    )


def send_documents_email(
    to_email: str,
    csp_name: str,
    csp_id: str,
    doc_names: List[str],
    doc_filepaths: List[str],
) -> bool:
    """Send generated documents to a CSP's email as attachments.

    Uses the same delivery method configured for OTP emails (SMTP/Gmail API/Console).

    Args:
        to_email: CSP's registered email address.
        csp_name: CSP's name for the greeting.
        csp_id: CSP ID for reference.
        doc_names: Human-readable document names.
        doc_filepaths: Paths to the generated DOCX files.

    Returns:
        True if email was sent successfully, False otherwise.
    """
    subject = f"Your CSP Documents — {csp_id} | EKO India Financial Services"
    html_body = _build_documents_html(csp_name, csp_id, doc_names)
    plain_body = _build_documents_plain(csp_name, csp_id, doc_names)

    method = settings.email_method.lower().strip()

    if method == "console":
        if not _console_allowed():
            return False
        logger.info(
            "email_service.send_documents_email: [CONSOLE MODE] "
            "Documents for CSP %s would be sent to %s (%d files)",
            csp_id, to_email, len(doc_filepaths),
        )
        print(f"\n{'='*50}")
        print(f"[CONSOLE EMAIL] To: {to_email}")
        print(f"[CONSOLE EMAIL] Subject: {subject}")
        print(f"[CONSOLE EMAIL] Attachments: {doc_filepaths}")
        print(f"{'='*50}\n")
        return True

    # Build email with attachments
    msg = MIMEMultipart("mixed")
    from_email = settings.smtp_from_email or settings.smtp_username or settings.gmail_sender_email
    msg["From"] = f"{settings.smtp_from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # Add body as alternative (HTML + plain text)
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(plain_body, "plain", "utf-8"))
    body_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(body_part)

    # Attach document files
    for filepath in doc_filepaths:
        if not os.path.isfile(filepath):
            logger.error(
                "email_service.send_documents_email: attachment file not found: %s",
                filepath,
            )
            return False

        filename = os.path.basename(filepath)
        try:
            with open(filepath, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={filename}")
            msg.attach(part)
        except Exception as e:
            logger.error(
                "email_service.send_documents_email: failed to attach %s: %s: %s",
                filepath, type(e).__name__, e,
            )
            return False

    # Send using existing transport
    if method == "smtp":
        try:
            if settings.smtp_use_tls:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
                server.ehlo()
                server.starttls()
                server.ehlo()
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)

            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
            server.quit()

            logger.info(
                "email_service.send_documents_email: documents sent to %s for CSP %s",
                to_email, csp_id,
            )
            return True
        except Exception as e:
            logger.error(
                "email_service.send_documents_email: SMTP error sending to %s: %s: %s",
                to_email, type(e).__name__, e,
            )
            return False

    elif method == "gmail_api":
        try:
            import base64
            from google.oauth2 import service_account as sa
            from googleapiclient.discovery import build

            credentials = sa.Credentials.from_service_account_file(
                settings.gmail_credentials_file,
                scopes=["https://www.googleapis.com/auth/gmail.send"],
            )
            delegated_creds = credentials.with_subject(settings.gmail_sender_email)
            service = build("gmail", "v1", credentials=delegated_creds)

            raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            service.users().messages().send(
                userId="me",
                body={"raw": raw_message},
            ).execute()

            logger.info(
                "email_service.send_documents_email: documents sent via Gmail API to %s for CSP %s",
                to_email, csp_id,
            )
            return True
        except Exception as e:
            logger.error(
                "email_service.send_documents_email: Gmail API error for %s: %s: %s",
                to_email, type(e).__name__, e,
            )
            return False

    else:
        logger.error(
            "email_service.send_documents_email: unknown EMAIL_METHOD '%s'.",
            method,
        )
        return False

