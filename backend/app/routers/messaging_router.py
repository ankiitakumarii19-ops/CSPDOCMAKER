"""
CSP DocMaker — how a workspace reaches its CSPs

Admins and Workspace Owners both work here. Deciding what a message says
and sending one is operational.

The one thing guarded harder than the rest is the send itself. Asking a
group of CSPs for their details reaches real people and cannot be taken
back, so a send names its recipients explicitly — there is no "everyone"
button — and the result says per person what happened.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import require_role
from app.models.csp_record import CSPRecord
from app.models.messaging import (
    CHANNEL_KINDS, PROVIDERS, PURPOSES, SENT, FAILED, PARTIAL,
    MessageCampaign, MessageChannel, MessageTemplate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/messaging", tags=["admin", "messaging"])


def _who(user: dict) -> str:
    return (user or {}).get("email") or (user or {}).get("sub") or "unknown"


class ChannelIn(BaseModel):
    name: str = Field(..., min_length=1)
    kind: str
    provider: str
    config: Dict = Field(default_factory=dict)
    secret_ref: Optional[str] = None
    is_default: bool = False
    active: bool = True


class TemplateIn(BaseModel):
    name: str = Field(..., min_length=1)
    purpose: str
    channel_kind: str = "whatsapp"
    subject: Optional[str] = None
    body: str = Field(..., min_length=1)
    languages: List[str] = Field(default_factory=list)
    active: bool = True


class SendRequest(BaseModel):
    """Who to ask. Named explicitly — there is deliberately no 'everyone'."""

    csp_ids: List[str] = Field(..., min_length=1, max_length=500)
    name: Optional[str] = None


@router.get("")
async def overview(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Channels, wording, and what has been sent."""
    channels = (await session.execute(
        select(MessageChannel).order_by(MessageChannel.name)
    )).scalars().all()
    templates = (await session.execute(
        select(MessageTemplate).order_by(MessageTemplate.purpose,
                                         MessageTemplate.name)
    )).scalars().all()
    campaigns = (await session.execute(
        select(MessageCampaign).order_by(MessageCampaign.created_at.desc())
        .limit(20)
    )).scalars().all()

    return {
        "channels": [
            {"id": str(c.id), "name": c.name, "kind": c.kind,
             "provider": c.provider, "is_default": c.is_default,
             "active": c.active, "secret_ref": c.secret_ref,
             "config": c.config or {}, "last_error": c.last_error,
             "last_used_at": c.last_used_at.isoformat()
                             if c.last_used_at else None,
             # Said plainly so nobody configures one and wonders why
             # nothing arrives. WhatsApp sends through Eko's platform
             # (D10) — it was wrongly shown as unable to (No. 174).
             "can_send": c.kind in ("email", "whatsapp")}
            for c in channels
        ],
        "templates": [
            {"id": str(t.id), "name": t.name, "purpose": t.purpose,
             "channel_kind": t.channel_kind, "subject": t.subject,
             "body": t.body, "languages": t.languages or [],
             "active": t.active, "is_builtin": t.is_builtin}
            for t in templates
        ],
        "campaigns": [
            {"id": str(c.id), "name": c.name, "status": c.status,
             "sent": c.sent_count, "failed": c.failed_count,
             "skipped": c.skipped_count,
             "recipients": len(c.recipients or []),
             "started_by": c.started_by,
             "created_at": c.created_at.isoformat()}
            for c in campaigns
        ],
        # What a person can send through right now, and why not (No. 174).
        "send_channels": _send_channels(),
        "channel_kinds": list(CHANNEL_KINDS),
        "providers": list(PROVIDERS),
        "purposes": list(PURPOSES),
    }


@router.post("/channels", status_code=status.HTTP_201_CREATED)
async def add_channel(
    body: ChannelIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Add a way of reaching people."""
    if body.kind not in CHANNEL_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Not a kind of channel: {body.kind!r}.")
    if body.provider not in PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Not a provider: {body.provider!r}.")

    existing = (await session.execute(
        select(MessageChannel).where(MessageChannel.name == body.name)
    )).scalars().first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A channel called {body.name!r} already exists.")

    if body.is_default:
        for other in (await session.execute(
            select(MessageChannel).where(MessageChannel.is_default.is_(True))
        )).scalars().all():
            other.is_default = False

    channel = MessageChannel(**body.model_dump())
    session.add(channel)
    await session.commit()
    logger.info("messaging_router.add_channel: %s added by %s",
                body.name, _who(user))
    return {"id": str(channel.id), "name": channel.name}


@router.patch("/channels/{channel_id}")
async def update_channel(
    channel_id: str,
    body: ChannelIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    channel = await _channel(session, channel_id)
    if body.is_default and not channel.is_default:
        for other in (await session.execute(
            select(MessageChannel).where(MessageChannel.is_default.is_(True))
        )).scalars().all():
            other.is_default = False
    for key, value in body.model_dump().items():
        setattr(channel, key, value)
    await session.commit()
    return {"id": channel_id, "name": channel.name}


@router.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    channel = await _channel(session, channel_id)
    await session.delete(channel)
    await session.commit()
    return {"deleted": channel_id}


@router.patch("/templates/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Change what a message says. A built-in can be edited, not removed."""
    template = await _template(session, template_id)
    for key, value in body.model_dump().items():
        setattr(template, key, value)
    await session.commit()
    logger.info("messaging_router.update_template: %s changed by %s",
                template.name, _who(user))
    return {"id": template_id, "name": template.name}


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def add_template(
    body: TemplateIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    if body.purpose not in PURPOSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Not a purpose: {body.purpose!r}.")
    template = MessageTemplate(is_builtin=False, **body.model_dump())
    session.add(template)
    await session.commit()
    return {"id": str(template.id), "name": template.name}


@router.get("/candidates")
async def candidates(
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Every CSP (No. 174: anyone can be messaged), with what they still
    miss, whether and when they were asked, and what would stop a send —
    on hold, unreachable, or (for the details form) an existing CSP."""
    from sqlalchemy import func

    from app.models.audit_log import AuditLog
    from app.models.data_request import DataRequest
    from app.models.source_sheet import SourceSheetState
    from app.services import field_ownership as fo
    from app.services.alert_composer import normalize_mobile

    asked = {}
    for r in (await session.execute(
            select(DataRequest).where(DataRequest.status.in_(("open", "answered")))
    )).scalars().all():
        if r.csp_id not in asked or r.created_at > asked[r.csp_id]:
            asked[r.csp_id] = r.created_at
    # A message a person sent (own words or a saved one) counts too, when
    # it went out — otherwise the label kept the old details-form date.
    for csp_id, at in (await session.execute(
            select(AuditLog.csp_id, func.max(AuditLog.created_at))
            .where(AuditLog.action == "csp_message",
                   AuditLog.result == "success", AuditLog.csp_id.isnot(None))
            .group_by(AuditLog.csp_id))).all():
        if csp_id not in asked or at > asked[csp_id]:
            asked[csp_id] = at
    imported = set((await session.execute(
        select(SourceSheetState.csp_code).where(
            SourceSheetState.imported_as.isnot(None)))).scalars())

    rows = []
    for record in (await session.execute(
            select(CSPRecord).order_by(CSPRecord.name))).scalars().all():
        missing = fo.missing(record)[fo.CSP]
        reachable = bool(normalize_mobile(record.mobile or "")
                         or (record.email or "").strip())
        code = record.csp_code or record.csp_id
        rows.append({
            "csp_id": record.csp_id,
            "name": record.name or "",
            "missing": [fo.label_of(f) for f in missing],
            "email": record.email or "",
            "mobile": record.mobile or "",
            "already_asked": record.csp_id in asked,
            "asked_at": asked[record.csp_id].isoformat()
                        if record.csp_id in asked else None,
            "reachable": reachable,
            "on_hold": record.send_hold or "",
            # In CSPDATA before the import: never the details form (D14).
            "existing": (record.origin or "") == "baseline" and code not in imported,
        })
    return {"candidates": rows, "total": len(rows)}


def _send_channels() -> list:
    from app.services import manual_messages
    return manual_messages.channels()


class MessageIn(BaseModel):
    """A message to these CSPs (No. 174). The screen sends a big selection
    in parts, so one request is at most 50 people."""

    csp_ids: List[str] = Field(..., min_length=1, max_length=50)
    kind: str = "custom"                   # custom | details_form
    channel: str = "whatsapp"              # whatsapp | email
    text: str = Field("", max_length=2000)
    template_id: Optional[str] = None
    name: Optional[str] = Field(None, max_length=200)


@router.post("/send-message")
async def send_message(
    body: MessageIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Send each named CSP the message, and say per person what happened.
    The rules are in services/manual_messages.py (on hold never; the details
    form never to an existing CSP; server only). Logged per message and as
    one campaign row."""
    from app.services import manual_messages as mm

    if body.kind not in (mm.CUSTOM, mm.DETAILS_FORM):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown message kind.")
    if body.kind == mm.CUSTOM and not body.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The message is empty.")
    who = _who(user).lower()

    def _send(sync):
        results = []
        for csp_id in body.csp_ids:
            record = sync.execute(select(CSPRecord).where(
                CSPRecord.csp_id == csp_id)).scalars().first()
            if record is None:
                results.append({"csp_id": csp_id, "sent": False,
                                "reason": "no such CSP"})
                continue
            results.append(mm.send(sync, record, kind=body.kind,
                                   channel=body.channel, text=body.text, by=who))
        sent = sum(1 for r in results if r.get("sent"))
        failed = len(results) - sent
        template_id = None
        if body.template_id:
            import uuid as _uuid
            try:
                template_id = _uuid.UUID(body.template_id)
            except ValueError:
                template_id = None
        sync.add(MessageCampaign(
            name=(body.name or f"Message to {len(body.csp_ids)} CSP(s)")[:200],
            template_id=template_id, recipients=list(body.csp_ids),
            status=SENT if failed == 0 else (PARTIAL if sent else FAILED),
            sent_count=sent, failed_count=failed,
            outcome={"kind": body.kind, "channel": body.channel,
                     "text": body.text[:1000], "results": results},
            started_by=who, finished_at=datetime.now(timezone.utc)))
        return results, sent, failed

    results, sent, failed = await session.run_sync(_send)
    await session.commit()
    logger.info("messaging_router.send_message: %s sent a %s %s message to "
                "%d CSP(s): %d sent, %d not", who, body.kind, body.channel,
                len(body.csp_ids), sent, failed)
    return {"asked": len(body.csp_ids), "sent": sent, "failed": failed,
            "results": results}


@router.post("/send")
async def send_now(
    body: SendRequest,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Ask these CSPs for their details, now.

    Runs synchronously and reports per person. A caller who has just told
    somebody "it has been sent" needs to know which ones actually were.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.services import message_sender as sender
    from app.workspace_context import current_workspace_id, workspace

    workspace_id = current_workspace_id()
    if workspace_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "No workspace for this request.")

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    results, sent, failed = [], 0, 0
    try:
        with workspace(workspace_id), Session(engine) as sync:
            try:
                channel = sender.choose_channel(sync)
                template = sender.choose_template(sync)
            except (sender.NoChannel, sender.NoTemplate) as e:
                raise HTTPException(status.HTTP_409_CONFLICT, str(e))

            for csp_id in body.csp_ids:
                record = sync.execute(
                    select(CSPRecord).where(CSPRecord.csp_id == csp_id)
                ).scalars().first()
                if record is None:
                    results.append({"csp_id": csp_id, "sent": False,
                                    "reason": "no such CSP"})
                    failed += 1
                    continue
                outcome = sender.ask_for_details(
                    sync, record, channel=channel, template=template,
                    manual=True)
                results.append(outcome)
                if outcome.get("sent"):
                    sent += 1
                else:
                    failed += 1

            campaign = MessageCampaign(
                name=body.name or f"Asked {len(body.csp_ids)} CSP(s)",
                template_id=template.id, channel_id=channel.id,
                recipients=list(body.csp_ids),
                status=SENT if failed == 0 else (PARTIAL if sent else FAILED),
                sent_count=sent, failed_count=failed,
                outcome={"results": results},
                started_by=_who(user),
                finished_at=datetime.now(timezone.utc),
            )
            sync.add(campaign)
            sync.commit()
    finally:
        engine.dispose()

    logger.info("messaging_router.send_now: %s asked %d, %d sent, %d not",
                _who(user), len(body.csp_ids), sent, failed)
    return {"asked": len(body.csp_ids), "sent": sent, "failed": failed,
            "results": results}


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(require_role("admin", "super_admin")),
):
    """Remove a saved message (No. 174). A supplied one cannot be removed —
    the app's own sends use it."""
    template = await _template(session, template_id)
    if template.is_builtin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "A supplied wording cannot be deleted; edit it instead.")
    await session.delete(template)
    await session.commit()
    logger.info("messaging_router.delete_template: %s deleted by %s",
                template.name, _who(user))
    return {"deleted": True}


async def _channel(session: AsyncSession, channel_id: str) -> MessageChannel:
    import uuid as _uuid
    try:
        key = _uuid.UUID(channel_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such channel.")
    channel = (await session.execute(
        select(MessageChannel).where(MessageChannel.id == key)
    )).scalars().first()
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such channel.")
    return channel


async def _template(session: AsyncSession, template_id: str
                    ) -> MessageTemplate:
    import uuid as _uuid
    try:
        key = _uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such template.")
    template = (await session.execute(
        select(MessageTemplate).where(MessageTemplate.id == key)
    )).scalars().first()
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such template.")
    return template
