"""
CSP DocMaker — what the ask-anything chat can look up and draft (No. 114)

The AI model never reaches the database itself. It asks for one of the
tools below by name; each runs with the signed-in person's own access, so
an RM's question is answered only from that RM's CSPs (csp_access — chosen
16 Oct 2026: "Everyone, RMs see only their CSPs"). A CSP someone may not
see is reported as not found, so the chat cannot be used to learn that it
exists.

Every tool returns two things:
  * `data`  — what the model reads to write its answer;
  * `card`  — what the chat screen shows under the answer (a CSP's
              contacts, Download buttons for its PDFs, a message draft
              with a Send button). Cards come from the database, not from
              the model's wording, so a number or file shown on a card is
              never one the model made up.

Drafting is the only "action", and it sends nothing: the draft is kept for
ASSISTANT_DRAFT_MINUTES and goes out only when the person presses Send
(chosen 16 Oct 2026). Sending is assistant_router's job.
"""

import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.csp_photo import CSPPhoto
from app.models.csp_record import CSPRecord
from app.models.enums import DocumentFormat
from app.models.stored_document import StoredDocument
from app.services import csp_access
from app.services.missing_data_service import document_label

logger = logging.getLogger(__name__)

WHATSAPP = "whatsapp"
EMAIL = "email"
MAX_MESSAGE_CHARS = 900

# The one WhatsApp wording every chat message travels in. Meta approves a
# wording once; the person's own text fills {message}, so later messages go
# out at once instead of each waiting for approval. Keep it stable.
WHATSAPP_WORDING = ("Namaste {name}, here is a message from Eko Bharat "
                    "Ventures: {message} Thank you.")
EMAIL_SUBJECT = "A message from Eko Bharat Ventures — CSP {code}"

# Contact and identity fields, as the CSP sheet names them.
CONTACT_FIELDS = [
    ("csp_code", "CSP Code"), ("name", "CSP Name"),
    ("mobile", "CSP Mobile Number"), ("email", "CSP Email Id"),
    ("branch_name", "Branch Name"), ("branch_code", "Branch Code"),
    ("branch_contact", "Branch Contact Number"), ("address", "Address"),
    ("district", "District"), ("state", "State"), ("lho", "LHO"),
    ("ao", "AO"), ("dc", "DC"), ("dc_email", "DC Email Id"),
    ("dc_contact", "DC Contact Number"), ("rbo_name", "RBO Name"),
    ("rbo_contact", "RBO Contact No."), ("rm_name", "Relationship Manager (RM)"),
    ("asm_name", "ASM"), ("asm_email", "ASM Email Id"),
    ("asm_contact", "ASM Contact Number"),
]

TOOLS = [
    {"type": "function", "function": {
        "name": "find_csps",
        "description": (
            "Search CSPs by part of their CSP code, name, mobile number, "
            "branch, district, state or RM name. Use when the person does "
            "not give an exact CSP code, or asks for a list."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string",
                      "description": "Text to search for"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "csp_details",
        "description": (
            "Everything on record for one CSP: its contacts and those of its "
            "branch, RBO, RM, ASM and DC, its address, and which documents "
            "and photo exist. Use for any question about one CSP."),
        "parameters": {"type": "object", "properties": {
            "csp_code": {"type": "string", "description": "The CSP code"}},
            "required": ["csp_code"]}}},
    {"type": "function", "function": {
        "name": "csp_documents",
        "description": (
            "The CSP's stored PDF documents (ID card, appointment letter, "
            "training certificate, BCP), shown to the person with Download "
            "buttons. Use whenever the person wants a CSP's documents."),
        "parameters": {"type": "object", "properties": {
            "csp_code": {"type": "string", "description": "The CSP code"}},
            "required": ["csp_code"]}}},
    {"type": "function", "function": {
        "name": "draft_message",
        "description": (
            "Prepare a WhatsApp or email message to a CSP. It is NOT sent: "
            "the person sees the draft and presses Send themselves. Write "
            "the message text the person asked for, politely, in English — "
            "in Hindi only if this request is written in Hindi/Hinglish or "
            "asks for Hindi. Do not add a greeting or sign-off; those are "
            "added automatically."),
        "parameters": {"type": "object", "properties": {
            "csp_code": {"type": "string", "description": "The CSP code"},
            "message": {"type": "string",
                        "description": "The message text, without greeting"},
            "channel": {"type": "string", "enum": [WHATSAPP, EMAIL, "auto"],
                        "description": "auto = WhatsApp if the CSP has a "
                                       "mobile number, else email"}},
            "required": ["csp_code", "message"]}}},
]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


class ToolError(ValueError):
    """A tool could not do what was asked; the text is shown to the model."""


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _value(v):
    if v is None or v == "":
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "value"):
        return v.value
    return v


def _scoped(query, user: dict):
    condition = csp_access.accessible_filter(user)
    return query if condition is None else query.where(condition)


async def find_one(session: AsyncSession, user: dict, code) -> CSPRecord:
    """The CSP with this code that the person may see, or ToolError."""
    code = _text(code)
    if not code:
        raise ToolError("No CSP code was given.")
    query = _scoped(select(CSPRecord).where(or_(
        func.lower(CSPRecord.csp_id) == code.lower(),
        func.lower(CSPRecord.csp_code) == code.lower())), user)
    csp = (await session.execute(query)).scalars().first()
    if csp is None:
        # Same answer whether it does not exist or belongs to another RM.
        raise ToolError(f"No CSP with code {code} was found"
                        + ("" if csp_access.is_admin(user)
                           else " among your CSPs") + ".")
    return csp


async def _documents(session: AsyncSession, csp_id: str) -> list:
    """Latest PDF of each document type, plus how many versions exist."""
    rows = (await session.execute(
        select(StoredDocument.id, StoredDocument.document_type,
               StoredDocument.version, StoredDocument.filename,
               StoredDocument.file_size, StoredDocument.created_at)
        .where(StoredDocument.csp_id == csp_id,
               StoredDocument.file_format == DocumentFormat.PDF)
        .order_by(StoredDocument.document_type,
                  StoredDocument.version.desc()))).all()
    latest, counts = {}, defaultdict(int)
    for r in rows:
        counts[r.document_type] += 1
        latest.setdefault(r.document_type, r)
    return [{"id": str(r.id), "document_type": _value(t),
             "label": document_label(t), "version": r.version,
             "versions": counts[t], "filename": r.filename,
             "size": r.file_size, "created_at": _value(r.created_at)}
            for t, r in latest.items()]


# ---- the tools --------------------------------------------------------------

async def find_csps(session, user, query) -> Tuple[dict, dict]:
    q = _text(query)
    if len(q) < 2:
        raise ToolError("Give at least two characters to search for.")
    like = f"%{q}%"
    base = _scoped(select(CSPRecord).where(or_(
        CSPRecord.csp_id.ilike(like), CSPRecord.csp_code.ilike(like),
        CSPRecord.name.ilike(like), CSPRecord.mobile.ilike(like),
        CSPRecord.branch_name.ilike(like), CSPRecord.district.ilike(like),
        CSPRecord.state.ilike(like), CSPRecord.rm_name.ilike(like))), user)
    total = (await session.execute(
        select(func.count()).select_from(base.subquery()))).scalar()
    csps = (await session.execute(
        base.order_by(CSPRecord.csp_id).limit(10))).scalars().all()
    items = [{"csp_code": c.csp_code or c.csp_id, "name": c.name,
              "district": c.district, "state": c.state,
              "branch_name": c.branch_name, "rm_name": c.rm_name}
             for c in csps]
    data = {"total_matches": total, "shown": len(items), "csps": items}
    return data, {"type": "csp_list", "query": q, "total": total,
                  "items": items}


async def csp_details(session, user, csp_code) -> Tuple[dict, dict]:
    csp = await find_one(session, user, csp_code)
    fields = [{"key": k, "label": label, "value": _value(getattr(csp, k, None))}
              for k, label in CONTACT_FIELDS]
    documents = await _documents(session, csp.csp_id)
    has_photo = (await session.execute(
        select(func.count()).select_from(CSPPhoto)
        .where(CSPPhoto.csp_id == csp.csp_id))).scalar() > 0
    data = {f["label"]: f["value"] for f in fields}
    data["Documents stored"] = [d["label"] for d in documents] or "none"
    data["Photo on file"] = has_photo
    return data, {"type": "csp", "csp_id": csp.csp_id,
                  "csp_code": csp.csp_code or csp.csp_id, "name": csp.name,
                  "fields": [f for f in fields if f["value"] is not None],
                  "documents": documents, "has_photo": has_photo}


async def csp_documents(session, user, csp_code) -> Tuple[dict, dict]:
    csp = await find_one(session, user, csp_code)
    documents = await _documents(session, csp.csp_id)
    data = {"csp_code": csp.csp_code or csp.csp_id, "name": csp.name,
            "documents": [{"name": d["label"], "version": d["version"]}
                          for d in documents]
            or "No documents are stored for this CSP yet."}
    return data, {"type": "documents", "csp_id": csp.csp_id,
                  "csp_code": csp.csp_code or csp.csp_id, "name": csp.name,
                  "documents": documents}


def whatsapp_number(csp: CSPRecord) -> str:
    from app.services import whatsapp_platform
    return whatsapp_platform.phone_for_whatsapp(csp.mobile or "")


def usable_email(csp: CSPRecord) -> str:
    email = _text(csp.email)
    return email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else ""


def preview_text(channel: str, csp: CSPRecord, message: str,
                 sender_name: str) -> str:
    """Exactly what the CSP will receive."""
    if channel == WHATSAPP:
        from app.services.whatsapp_platform import one_line
        return WHATSAPP_WORDING.format(name=one_line(csp.name or "CSP"),
                                       message=one_line(message))
    return (f"Namaste {csp.name or 'CSP'},\n\n{message}\n\n"
            f"— {sender_name}\nEko Bharat Ventures Pvt Ltd")


async def draft_message(session, user, csp_code, message, channel="auto"
                        ) -> Tuple[dict, dict]:
    csp = await find_one(session, user, csp_code)
    message = _text(message)
    if not message:
        raise ToolError("The message is empty — ask what to say.")
    if message[-1] not in ".!?।":
        message += "."  # the wording's "Thank you." follows it
    if len(message) > MAX_MESSAGE_CHARS:
        raise ToolError(f"The message is {len(message)} characters; keep it "
                        f"under {MAX_MESSAGE_CHARS}.")
    channel = _text(channel).lower() or "auto"
    mobile, email = whatsapp_number(csp), usable_email(csp)
    if channel == "auto":
        channel = WHATSAPP if mobile else EMAIL
    if channel not in (WHATSAPP, EMAIL):
        raise ToolError(f"Unknown channel {channel!r}; use whatsapp or email.")
    to = mobile if channel == WHATSAPP else email
    if not to:
        other = EMAIL if channel == WHATSAPP else WHATSAPP
        raise ToolError(
            f"CSP {csp.csp_code or csp.csp_id} has no usable "
            f"{'mobile number' if channel == WHATSAPP else 'email address'}"
            + (f"; {other} is possible instead."
               if (email if other == EMAIL else mobile) else
               ", and no other way to reach them is on record."))

    sender = _text(user.get("name")) or _text(user.get("sub"))
    minutes = get_settings().assistant_draft_minutes
    draft = {
        "id": uuid.uuid4().hex,
        "csp_id": csp.csp_id, "csp_code": csp.csp_code or csp.csp_id,
        "csp_name": csp.name, "channel": channel, "to": to,
        "message": message,
        "preview": preview_text(channel, csp, message, sender),
        "subject": (EMAIL_SUBJECT.format(code=csp.csp_code or csp.csp_id)
                    if channel == EMAIL else None),
        "owner": _text(user.get("sub")).lower(),
        "sender_name": sender,
        "workspace_id": _workspace_text(),
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(minutes=minutes)).isoformat(),
    }
    await save_draft(draft, minutes)
    data = {"status": "DRAFT ONLY — NOT SENT. The person must press Send.",
            "to": f"{csp.name} ({draft['csp_code']}) by {channel}",
            "text": draft["preview"]}
    return data, {"type": "draft", **_public(draft)}


def _public(draft: dict) -> dict:
    """The draft as the screen may show it (no owner or workspace)."""
    return {k: draft[k] for k in (
        "id", "csp_id", "csp_code", "csp_name", "channel", "to", "preview",
        "subject", "expires_at")}


def _workspace_text() -> str:
    from app.workspace_context import current_workspace_id
    wid = current_workspace_id()
    return str(wid) if wid else ""


# ---- drafts, kept in Redis until Send or expiry ------------------------------

_DRAFT_KEY = "assistant:draft:{}"
_redis = None


def _client():
    global _redis
    if _redis is None:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(get_settings().redis_url,
                                   decode_responses=True)
    return _redis


async def save_draft(draft: dict, minutes: int) -> None:
    try:
        await _client().set(_DRAFT_KEY.format(draft["id"]), json.dumps(draft),
                            ex=max(60, minutes * 60))
    except Exception as e:
        logger.error("assistant_tools.save_draft: could not keep draft %s for "
                     "CSP %s: %s: %s", draft["id"], draft["csp_id"],
                     type(e).__name__, e, exc_info=True)
        raise ToolError(f"The draft could not be kept (Redis: "
                        f"{type(e).__name__}); nothing was sent.") from e


async def take_draft(draft_id: str) -> Optional[dict]:
    """Remove and return a draft — atomically, so one draft is sent once."""
    if not re.fullmatch(r"[0-9a-f]{32}", draft_id or ""):
        return None
    raw = await _client().getdel(_DRAFT_KEY.format(draft_id))
    return json.loads(raw) if raw else None


async def put_back(draft: dict) -> None:
    """A send that definitely did not go out may be tried again."""
    left = (datetime.fromisoformat(draft["expires_at"])
            - datetime.now(timezone.utc)).total_seconds()
    if left > 5:
        await _client().set(_DRAFT_KEY.format(draft["id"]), json.dumps(draft),
                            ex=int(left))


# ---- dispatch ----------------------------------------------------------------

async def run(name: str, arguments, session: AsyncSession, user: dict
              ) -> Tuple[dict, Optional[dict]]:
    """Run one tool the model asked for. Never raises for a bad request from
    the model — the reason goes back to the model as data — but does raise
    for failures of the app itself, which the router reports."""
    if name not in TOOL_NAMES:
        return {"error": f"There is no tool called {name!r}."}, None
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except ValueError:
            return {"error": "The tool arguments were not valid JSON."}, None
    if not isinstance(arguments, dict):
        return {"error": "The tool arguments must be an object."}, None
    try:
        if name == "find_csps":
            return await find_csps(session, user, arguments.get("query"))
        if name == "csp_details":
            return await csp_details(session, user, arguments.get("csp_code"))
        if name == "csp_documents":
            return await csp_documents(session, user,
                                       arguments.get("csp_code"))
        return await draft_message(
            session, user, arguments.get("csp_code"),
            arguments.get("message"), arguments.get("channel") or "auto")
    except ToolError as e:
        return {"error": str(e)}, None
