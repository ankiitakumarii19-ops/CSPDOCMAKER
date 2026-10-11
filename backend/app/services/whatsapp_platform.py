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
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SENT = "sent"
PENDING = "pending"          # template submitted / awaiting Meta's approval
REJECTED = "rejected"
FAILED = "failed"

# The app's own placeholders in its stored wording.
_TOKEN = re.compile(r"\{(name|fields|link|documents|email)\}")


class WhatsAppPlatformError(RuntimeError):
    """The platform could not be reached or answered with an error."""


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
                timeout=s.whatsapp_platform_timeout_seconds,
            )
            telemetry.note_http(span, "whatsapp_platform", op,
                                response.status_code, ok_statuses=(200,))
    except Exception as e:
        raise WhatsAppPlatformError(
            f"WhatsApp platform unreachable: {type(e).__name__}: {e}") from e
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
         category: str = "UTILITY") -> dict:
    """Send one person one message. Never raises.

    Returns {"status": SENT|PENDING|REJECTED|FAILED, "reason": str,
             "job_id": str|None, "template_name": str|None}.
    """
    phone = phone_for_whatsapp(to_mobile)
    if not phone:
        return _result(FAILED, f"not a usable mobile number: {to_mobile!r}")

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
        answer = call_tool("smart_send_template", arguments)
    except WhatsAppPlatformError as e:
        logger.warning("whatsapp_platform.send: %s", e)
        return _result(FAILED, str(e))

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


def _result(status, reason="", job_id=None, template_name=None) -> dict:
    return {"status": status, "reason": reason, "job_id": job_id,
            "template_name": template_name}


def delivery_status(job_id: str) -> dict:
    """Meta's own delivered/read status for a past send."""
    return call_tool("get_delivery_status", {"job_id": job_id})
