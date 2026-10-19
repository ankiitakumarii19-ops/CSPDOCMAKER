"""
CSP DocMaker — what the ask-anything chat can look up and draft (No. 114)

assistant_engine (rules, no AI model since No. 116) calls these. Each runs
with the signed-in person's own access, so an RM's question is answered
only from that RM's CSPs (csp_access — chosen 16 Oct 2026: "Everyone, RMs
see only their CSPs"). A CSP someone may not see is reported as not found,
so the chat cannot be used to learn that it exists.

Every lookup returns two things:
  * `data`  — the facts, as plain values;
  * `card`  — what the chat screen shows under the answer (a CSP's
              contacts, Download buttons for its PDFs, a message draft
              with a Send button), straight from the database.

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

class ToolError(ValueError):
    """A lookup could not do what was asked; the text is the chat's answer."""


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
                 sender_name: str,
                 organisation: str = "Eko Bharat Ventures Pvt Ltd") -> str:
    """Exactly what the CSP will receive. The email's last line is the
    workspace's sign-off (No. 120); the WhatsApp wording is the one Meta
    approved and stays fixed."""
    if channel == WHATSAPP:
        from app.services.whatsapp_platform import one_line
        return WHATSAPP_WORDING.format(name=one_line(csp.name or "CSP"),
                                       message=one_line(message))
    return (f"Namaste {csp.name or 'CSP'},\n\n{message}\n\n"
            f"— {sender_name}\n{organisation}")


async def _organisation(session) -> str:
    """The email sign-off line: the workspace's chosen sign-off; otherwise
    Eko's company name for Eko and the workspace's name for any other."""
    from app.models.workspace import Workspace
    from app.services import workspace_rules, workspace_service
    from app.workspace_context import current_workspace_id
    ws = (await session.execute(select(Workspace).where(
        Workspace.id == current_workspace_id()))).scalars().first()
    if ws is None:
        return "Eko Bharat Ventures Pvt Ltd"
    if workspace_rules.signoff(ws):
        return workspace_rules.signoff(ws)
    if await workspace_service.is_eko(session, ws.id):
        return "Eko Bharat Ventures Pvt Ltd"
    return ws.name


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
        "preview": preview_text(channel, csp, message, sender,
                                await _organisation(session)),
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


# ---- setup actions, kept until the Owner presses Do it (No. 117) -------------

_ACTION_KEY = "assistant:action:{}"


async def propose_action(user: dict, kind: str, params: dict, title: str,
                         detail: str, extra=()) -> dict:
    """Keep a setup action the chat offers to do, and return its card. It
    runs only when the same person presses Do it (assistant_router)."""
    minutes = get_settings().assistant_draft_minutes
    action = {
        "id": uuid.uuid4().hex, "kind": kind, "params": params,
        "title": title, "detail": detail, "extra": list(extra),
        "owner": _text(user.get("sub")).lower(),
        "workspace_id": _workspace_text(),
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(minutes=minutes)).isoformat(),
    }
    try:
        await _client().set(_ACTION_KEY.format(action["id"]),
                            json.dumps(action), ex=max(60, minutes * 60))
    except Exception as e:
        logger.error("assistant_tools.propose_action: could not keep the %s "
                     "action: %s: %s", kind, type(e).__name__, e,
                     exc_info=True)
        raise ToolError(f"The action could not be kept (Redis: "
                        f"{type(e).__name__}); nothing was changed.") from e
    return {"type": "action", **{k: action[k] for k in (
        "id", "kind", "title", "detail", "extra", "expires_at")}}


async def take_action(action_id: str) -> Optional[dict]:
    """Remove and return an action — atomically, so it runs once."""
    if not re.fullmatch(r"[0-9a-f]{32}", action_id or ""):
        return None
    raw = await _client().getdel(_ACTION_KEY.format(action_id))
    return json.loads(raw) if raw else None


async def put_back_action(action: dict) -> None:
    """Someone else's press must not use up the owner's action."""
    left = (datetime.fromisoformat(action["expires_at"])
            - datetime.now(timezone.utc)).total_seconds()
    if left > 5:
        await _client().set(_ACTION_KEY.format(action["id"]),
                            json.dumps(action), ex=int(left))
