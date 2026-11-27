"""
CSP DocMaker — WhatsApp through Eko's internal WhatsApp Bulk Sender

Chosen 12 Oct 2026 (tracker No. 77/78). Eko runs its own platform on top of
Meta's WhatsApp Cloud API: it creates the message template, waits for Meta to
approve it, and sends. This app talks to its hosted connection
(WHATSAPP_PLATFORM_URL), which already carries Eko's shared key — so no
password for it is stored here.

What the platform requires, and this module takes care of:

  * Every business-started message uses a template Meta has approved. A new
    wording is submitted automatically; until Meta approves it the answer is
    "pending" (minutes to about a day) and nothing is sent. Asking again with
    the SAME wording later sends it — so the wording is kept stable.
  * Placeholders are numbered ({{1}}, {{2}}, ...) and may not be the very
    first or last thing in the message.
  * A filled-in value may not contain a line break.
  * Phone numbers carry the country code, digits only (91XXXXXXXXXX).
  * An attached document is fetched by the platform from a public URL.

Nothing here decides WHO is messaged or WHEN — message_sender does that,
with its guards (no localhost links, nobody asked twice, large groups need
approval). This module only puts one message on the wire and says plainly
what happened.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SENT = "sent"
PENDING = "pending"          # template submitted / awaiting Meta's approval
REJECTED = "rejected"
FAILED = "failed"

# The app's own placeholders in its stored wording.
# {message} is the ask-anything chat's own text (No. 114).
_TOKEN = re.compile(r"\{(name|fields|link|documents|email|message)\}")


class WhatsAppPlatformError(RuntimeError):
    """The platform could not be reached or answered with an error.
    timed_out: it was reached but did not answer in time (No. 268) — it may
    still have done what it was asked."""

    def __init__(self, message: str, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out


def _timeout(s):
    """No. 268 (27 Nov 2026): the platform works through one request at a
    time, so a single message waits behind another team's bulk batch (100
    messages take about 2.5 minutes). 60 seconds was too short — 11:31 IST
    sends failed with ReadTimeout while batches were going. Now: up to
    WHATSAPP_PLATFORM_TIMEOUT_SECONDS (300) for the answer, but only
    WHATSAPP_PLATFORM_CONNECT_TIMEOUT_SECONDS (15) to reach it, so a platform
    that is really down still fails fast."""
    import httpx
    return httpx.Timeout(float(s.whatsapp_platform_timeout_seconds),
                         connect=float(s.whatsapp_platform_connect_timeout_seconds))


def _settings():
    from app.config import get_settings
    return get_settings()


def _rpc(method: str, params: dict, request_id: int = 1) -> dict:
    """One JSON-RPC call to the hosted connection. Raises on any failure."""
    import httpx

    from app import telemetry

    s = _settings()
    op = params.get("name") or method
    try:
        with telemetry.external_call("whatsapp_platform", op) as span:
            response = httpx.post(
                s.whatsapp_platform_url,
                json={"jsonrpc": "2.0", "id": request_id, "method": method,
                      "params": params},
                headers={"Content-Type": "application/json",
                         "Accept": "application/json, text/event-stream"},
                timeout=_timeout(s),
            )
            telemetry.note_http(span, "whatsapp_platform", op,
                                response.status_code, ok_statuses=(200,))
    except Exception as e:
        raise WhatsAppPlatformError(
            f"WhatsApp platform unreachable: {type(e).__name__}: {e}",
            timed_out=isinstance(e, (httpx.ReadTimeout, httpx.WriteTimeout,
                                     httpx.PoolTimeout))) from e
    if response.status_code != 200:
        raise WhatsAppPlatformError(
            f"WhatsApp platform answered HTTP {response.status_code}: "
            f"{response.text[:300]}")

    # The reply is JSON, or a server-sent event whose data line is JSON.
    text = response.text.strip()
    payload = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                break
            except ValueError:
                continue
    if payload is None:
        logger.error("whatsapp_platform: reply not understood (malformed): %s",
                     text[:300], extra={"failure_kind": "malformed"})
        raise WhatsAppPlatformError(
            f"WhatsApp platform reply not understood: {text[:300]}")
    if "error" in payload:
        raise WhatsAppPlatformError(
            f"WhatsApp platform error: {payload['error']}")
    return payload.get("result") or {}


def call_tool(name: str, arguments: dict) -> dict:
    """Call one platform tool and return its result as a dict."""
    result = _rpc("tools/call", {"name": name, "arguments": arguments})
    if result.get("isError"):
        raise WhatsAppPlatformError(
            f"{name} failed: {_text_of(result)[:500]}")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        # Some servers wrap a plain value as {"result": ...}.
        inner = structured.get("result")
        return inner if isinstance(inner, dict) else structured
    text = _text_of(result)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {"value": value}
    except ValueError:
        return {"text": text}


def upload_media(path: str) -> str:
    """Give the platform a local file (PDF, image, MP4 video up to 16 MB) to
    send as a message's media header. Returns its `ref` ("wamedia://...") —
    used as header_media_url; no public link needed (No. 212). Raises
    WhatsAppPlatformError when the platform refuses."""
    import base64

    with open(path, "rb") as fh:
        data = base64.b64encode(fh.read()).decode("ascii")
    answer = call_tool("upload_media", {"file_base64": data,
                                        "filename": os.path.basename(path)})
    ref = answer.get("ref")
    if not ref:
        raise WhatsAppPlatformError(f"upload_media gave no ref: {str(answer)[:300]}")
    return ref


def _text_of(result: dict) -> str:
    return "".join(c.get("text", "") for c in result.get("content", [])
                   if isinstance(c, dict))


# ---- wording ---------------------------------------------------------------

def to_template(body: str) -> Tuple[str, Dict[str, dict], List[str]]:
    """The app's wording as a WhatsApp template.

    "Namaste {name} ... {link}" becomes "Namaste {{1}} ... {{2}}", with a
    mapping telling the platform which contact column fills each number.
    Every occurrence gets its own number (a name used three times is
    {{1}}, {{3}}, {{5}}), which Meta always accepts.
    """
    mapping: Dict[str, dict] = {}
    columns: List[str] = []
    counter = 0

    def number(match):
        nonlocal counter
        counter += 1
        column = match.group(1)
        mapping[str(counter)] = {"type": "column", "value": column}
        if column not in columns:
            columns.append(column)
        return "{{%d}}" % counter

    return _TOKEN.sub(number, body), mapping, columns


def one_line(value: str) -> str:
    """Meta refuses a filled-in value containing a line break."""
    return re.sub(r"\s*[\r\n]+\s*", " / ", (value or "").strip())


def phone_for_whatsapp(mobile: str) -> str:
    """91XXXXXXXXXX from whatever the sheet holds, or '' if unusable."""
    digits = re.sub(r"\D", "", mobile or "")
    if len(digits) == 10:
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    return digits if len(digits) == 12 and digits.startswith("91") else ""


# ---- sending ---------------------------------------------------------------

def send(to_mobile: str, body: str, values: Dict[str, str], *,
         source_name: str, document_url: Optional[str] = None,
         category: str = "UTILITY", force: bool = False,
         media_type: Optional[str] = None,
         media_url: Optional[str] = None) -> dict:
    """Send one person one message. Never raises.

    media_type / media_url (No. 257): a photo ("image"), video ("video") or
    file ("document") as the message's header - the platform's ref from
    upload_media. document_url is the older way to attach a PDF.

    Returns {"status": SENT|PENDING|REJECTED|FAILED, "reason": str,
             "job_id": str|None, "template_name": str|None}.
    """
    if _settings().test_copy:
        # The one place every WhatsApp goes through (No. 173).
        logger.info("whatsapp_platform.send: not sent — this is a test copy "
                    "(TEST_COPY=true)")
        return _result(FAILED, "TEST_COPY: nothing is sent from the test copy")
    # No. 215: paused / not live yet / test mode (only the test number).
    from app.services import send_guard
    real = to_mobile
    to_mobile, refused = send_guard.whatsapp_to(to_mobile)
    if refused:
        return _result(FAILED, f"waiting: {refused}")
    phone = phone_for_whatsapp(to_mobile)
    if not phone:
        return _result(FAILED, f"not a usable mobile number: {to_mobile!r}")
    if to_mobile != real:
        logger.info("whatsapp_platform.send: test mode — sent to the test "
                    "number instead of %s", real)

    # No. 213: the most of the app's own messages one number gets a day.
    from app.services import send_reason
    if not (force or send_reason.current_person()):
        cap = int(getattr(_settings(), "send_max_per_person_day", 0) or 0)
        if cap and sent_today(phone) >= cap:
            return _result(FAILED, f"waiting: {cap} message(s) already went "
                                   "to this number today (Settings → "
                                   "Sending hours)")
    # No. 216: the workspace's ceiling for a day, whoever sends.
    ceiling = int(getattr(_settings(), "max_whatsapp_per_day", 0) or 0)
    if ceiling and sent_today(None) >= ceiling:
        return _result(FAILED, f"waiting: this workspace's ceiling of "
                               f"{ceiling} WhatsApps today is reached "
                               "(Settings → Going live)")

    template, mapping, columns = to_template(body)
    contact = {"phone": phone}
    for column in columns:
        contact[column] = one_line(values.get(column, ""))
    s = _settings()
    try:
        job = call_tool("upload_contacts", {
            "contacts": [contact], "source_name": source_name})
        job_id = job.get("job_id")
        if not job_id:
            return _result(FAILED, f"no job_id from upload_contacts: {job}")
        arguments = {
            "job_id": job_id, "phone_column": "phone", "body": template,
            "mapping": mapping, "category": category,
            "language": s.whatsapp_language,
        }
        if document_url:
            arguments.update(header_type="document",
                             header_media_url=document_url)
        elif media_type and media_url:
            arguments.update(header_type=media_type,
                             header_media_url=media_url)
        # No. 195: the platform refuses the same text to the same number
        # within 15 minutes ("duplicate blast"). A message a PERSON sends
        # (Admin, Super Admin, RM — send_reason.sent_by) is meant, so it is
        # sent anyway; the app's own messages keep that protection.
        from app.services import send_reason
        if force or send_reason.current_person():
            arguments["force"] = True
        try:
            answer = call_tool("smart_send_template", arguments)
        except WhatsAppPlatformError as e:
            if e.timed_out:
                return _after_timeout(job_id, e)
            if not _template_lookup_missed(e):
                raise
            return _send_by_name(job_id, arguments, template, e)
    except WhatsAppPlatformError as e:
        logger.warning("whatsapp_platform.send: %s", e)
        return _result(FAILED, _plain_timeout(e))

    action = str(answer.get("action", "")).lower()
    name = answer.get("template_name")
    if action == "sent":
        if int(answer.get("sent", 1) or 0) >= 1:
            return _result(SENT, "", job_id, name)
        return _result(FAILED, f"platform accepted but sent 0: {answer}",
                       job_id, name)
    if action in ("created", "pending"):
        return _result(PENDING, "waiting for Meta to approve the message "
                       "wording (minutes to about a day); it is sent "
                       "automatically on a later try", job_id, name)
    if action == "rejected":
        return _result(REJECTED, f"Meta rejected the wording: "
                       f"{answer.get('reason', '')}", job_id, name)
    return _result(FAILED, f"unexpected answer: {str(answer)[:300]}",
                   job_id, name)


# ---- when the platform cannot find a template it made (No. 189) ------------
#
# smart_send_template looks for an existing template among the first 100 on
# Eko's Meta account only. Once other teams' templates push this app's
# approved ones past that, it does not find them, tries to create them again
# under the same name, and Meta answers "There is already English (US)
# content for this template". The template exists (usually approved), so it
# is sent by its name instead. Remove once the platform reads every page.

_ALREADY_EXISTS = re.compile(r"already .{0,40}content for this template", re.I)


def sent_today(phone: Optional[str]) -> int:
    """The app's own WhatsApps sent to this number since midnight (on the
    workspace's clock); phone None = every WhatsApp the workspace sent
    today, by anyone (No. 216). 0 if it cannot be counted (logged)."""
    from datetime import datetime, timezone
    from sqlalchemy import create_engine, text
    from app.workers.verify_old_csps_worker import send_zone
    from app.workspace_context import current_workspace_id
    zone = send_zone()
    midnight = datetime.now(timezone.utc).astimezone(zone).replace(
        hour=0, minute=0, second=0, microsecond=0)
    engine = create_engine(_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with engine.connect() as conn:
            if phone is None:
                return int(conn.execute(text(
                    "SELECT count(*) FROM whatsapp_messages WHERE sent_at >= "
                    ":t AND send_status = 'sent' AND workspace_id = :w"), {
                        "t": midnight,
                        "w": str(current_workspace_id())}).scalar() or 0)
            return int(conn.execute(text(
                "SELECT count(*) FROM whatsapp_messages WHERE right(phone, 10)"
                " = right(:p, 10) AND sent_at >= :t AND sent_by IS NULL AND "
                "send_status = 'sent' AND workspace_id = :w"), {
                    "p": phone, "t": midnight,
                    "w": str(current_workspace_id())}).scalar() or 0)
    except Exception as e:
        logger.error("whatsapp_platform.sent_today: could not count (%s: %s)"
                     " — not limiting", type(e).__name__, e)
        return 0
    finally:
        engine.dispose()


def _template_lookup_missed(error: Exception) -> bool:
    return bool(_ALREADY_EXISTS.search(str(error)))


def platform_template_name(template_body: str) -> str:
    """The name the platform gives a wording it submits: "auto_" + the first
    16 hex characters of the MD5 of the wording with runs of spaces / line
    breaks made one space. Checked 17 Nov 2026 against every auto_ template
    on the account (data verification = auto_e72d2d9e338ad3c9)."""
    import hashlib

    squeezed = " ".join(template_body.split())
    return "auto_" + hashlib.md5(squeezed.encode("utf-8")).hexdigest()[:16]


def _send_by_name(job_id: str, arguments: dict, template_body: str,
                  first_error: Exception) -> dict:
    """Send the existing template by its name. Never raises.

    Only reached when smart_send_template refused before sending anything,
    so this cannot send the same message twice.
    """
    name = platform_template_name(template_body)
    logger.warning(
        "whatsapp_platform.send: the platform did not find template %s "
        "(Meta: already exists) — sending it by name instead (No. 189)",
        name, extra={"failure_kind": "platform_template_lookup"})
    by_name = {k: v for k, v in arguments.items()
               if k not in ("body", "category")}
    by_name["template_name"] = name
    try:
        answer = call_tool("send_template_message", by_name)
    except WhatsAppPlatformError as e:
        if e.timed_out:
            return _after_timeout(job_id, e, name)
        logger.warning("whatsapp_platform.send: sending %s by name failed "
                       "too: %s", name, e)
        return _result(FAILED, f"{first_error} — then sending the existing "
                       f"template {name} by name failed: {e}", job_id, name)
    if int(answer.get("sent", 0) or 0) >= 1:
        return _result(SENT, "", job_id, name)
    return _result(FAILED, f"sending the existing template {name} by name "
                   f"sent 0: {str(answer)[:300]}", job_id, name)


def _plain_timeout(error: Exception) -> str:
    """The reason shown on the WhatsApp messages screen; a timeout says
    plainly that the platform was busy (No. 268). The original text stays
    in it, so resend_failed still sees it as the platform's fault."""
    if getattr(error, "timed_out", False):
        return (f"{error} — the platform did not answer in "
                f"{_settings().whatsapp_platform_timeout_seconds} s (busy, "
                "e.g. another team's bulk sending); it is sent again "
                "automatically")
    return str(error)


def _after_timeout(job_id: str, error: "WhatsAppPlatformError",
                   template_name: Optional[str] = None) -> dict:
    """The send step was asked but its answer did not come in time (No. 268).
    The platform may still have sent it, so ask it before calling it failed
    — otherwise it would be sent again later and the CSP would get it twice.
    Never raises."""
    try:
        status = delivery_status(job_id)
    except Exception as e:
        logger.warning("whatsapp_platform.send: %s; could not check whether "
                       "job %s went (%s: %s) — counted as not sent",
                       error, job_id, type(e).__name__, e)
        return _result(FAILED, _plain_timeout(error), job_id, template_name)
    rows = status.get("rows") or []
    if any(str(r.get("sent_status", "")).lower() == "sent" for r in rows):
        logger.info("whatsapp_platform.send: the platform answered late "
                    "(%s) but job %s was sent", error, job_id)
        return _result(SENT, "", job_id, template_name)
    logger.warning("whatsapp_platform.send: %s; job %s shows nothing sent",
                   error, job_id)
    return _result(FAILED, _plain_timeout(error), job_id, template_name)


def _result(status, reason="", job_id=None, template_name=None) -> dict:
    return {"status": status, "reason": reason, "job_id": job_id,
            "template_name": template_name}


def delivery_status(job_id: str) -> dict:
    """Meta's own delivered/read status for a past send."""
    return call_tool("get_delivery_status", {"job_id": job_id})
