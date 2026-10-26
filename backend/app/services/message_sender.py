"""
CSP DocMaker — putting a message on the wire

The piece that was missing. Everything else existed: the agent that decides
who needs asking, the channel a workspace configured, the wording, and the
tokenised link. Nothing actually sent.

Email is implemented because it works today — SMTP is already how documents
reach CSPs, it needs no provider approval, and most CSPs have an address on
file. WhatsApp goes through Eko's internal WhatsApp Bulk Sender platform
(whatsapp_platform.py, tracker No. 78), which handles Meta's template
approval.

Three rules this holds to:

  * Nobody is messaged twice about the same thing. An open request means
    they have already been asked and are being waited on.
  * A CSP with no usable address is reported, not silently skipped. Their
    RM has to collect the details some other way, and should be told.
  * Every attempt is recorded on the request, so an unanswered ask can be
    told apart from one that never arrived.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.data_request import VIA_EMAIL, VIA_WHATSAPP
from app.models.messaging import (
    EMAIL, PURPOSE_DATA_REQUEST, PURPOSE_MISSING_DATA, WHATSAPP,
    MessageChannel, MessageTemplate,
)
from app.services import data_request_service as drs
from app.services import field_ownership as fo
from app import telemetry

logger = logging.getLogger(__name__)


class NoChannel(RuntimeError):
    """This workspace has not said how it reaches people."""


class NoTemplate(RuntimeError):
    """This workspace has not said what the message says."""


# ---- filling the wording -------------------------------------------------

def render(body: str, *, name: str, link: str, fields: List[str]) -> str:
    """Substitute what varies, and leave everything else alone.

    Only three placeholders are recognised. A stray brace in a customer's
    own wording must not blank their message, so anything unrecognised is
    passed through untouched rather than erroring or emptying.
    """
    readable = ", ".join(fo.label_of(f) for f in fields) if fields else ""
    out = body
    for token, value in (("{name}", name), ("{link}", link),
                         ("{fields}", readable)):
        out = out.replace(token, value)
    return out


# A link nobody outside this machine can open.
#
# PUBLIC_APP_URL defaults to localhost so the system runs on a laptop
# without configuration. Sending someone a localhost link is worse than
# not sending: they get a message that looks official, cannot act on it,
# and the request is marked as asked. So it is refused until the address
# is a real one.
UNREACHABLE_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def link_is_reachable(link: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(link).hostname or "").lower()
    return bool(host) and host not in UNREACHABLE_HOSTS


def why_unreachable(link: str) -> str:
    # Names the address only: the full link carries the CSP's private token,
    # and this reason is shown on screens and stored as the channel's error.
    from urllib.parse import urlparse

    parts = urlparse(link)
    return (
        f"the app is at {parts.scheme}://{parts.netloc}, which nobody "
        f"outside this machine can open, so the CSP could not use the form "
        f"link. Set PUBLIC_APP_URL to a real address before messaging "
        f"anyone."
    )


def choose_channel(session: Session, kind: Optional[str] = None
                   ) -> MessageChannel:
    """The channel to send through, preferring the default."""
    query = select(MessageChannel).where(MessageChannel.active.is_(True))
    if kind:
        query = query.where(MessageChannel.kind == kind)
    channels = session.execute(
        query.order_by(MessageChannel.is_default.desc(),
                       MessageChannel.created_at)
    ).scalars().all()
    if not channels:
        raise NoChannel(
            "No active messaging channel is configured for this workspace. "
            "Add one before anything can be sent."
        )
    return channels[0]


def choose_template(session: Session, purpose: str = PURPOSE_DATA_REQUEST
                    ) -> MessageTemplate:
    template = session.execute(
        select(MessageTemplate).where(
            MessageTemplate.purpose == purpose,
            MessageTemplate.active.is_(True),
        ).order_by(MessageTemplate.is_builtin, MessageTemplate.created_at)
    ).scalars().first()
    if template is None:
        raise NoTemplate(
            f"No active message template for {purpose!r}. Add one before "
            f"anything can be sent."
        )
    return template


def template_for(session: Session, record, verify: bool = False
                 ) -> MessageTemplate:
    """The wording for this ask.

    A CSP who has already submitted a form and still left something blank
    is told what is missing ("these details are still needed: …"), not sent
    "please confirm your details" again (23 Oct 2026, No. 139). Before, the
    new-CSP job sent the same verification wording minutes after the CSP
    had answered it, and the WhatsApp platform refused it as a duplicate.
    """
    if verify or not drs.has_answered(session, record.csp_id):
        return choose_template(session)
    try:
        return choose_template(session, PURPOSE_MISSING_DATA)
    except NoTemplate as e:
        logger.warning("message_sender.template_for: CSP %s — %s Using the "
                       "confirm-your-details wording instead.",
                       record.csp_id, e)
        return choose_template(session)


# ---- actually sending ----------------------------------------------------

def _send_email(to: str, subject: str, body: str, *,
                kind: str = "other", csp_id: Optional[str] = None,
                csp_name: Optional[str] = None) -> Tuple[bool, str]:
    """Send plain text through the existing SMTP path, and record it
    (No. 127): sent or failed, and later opened / bounced."""
    from app.services import email_log, email_service

    if email_service.paused():
        logger.info("message_sender: email to %s not sent — emails are "
                    "paused", to)
        return False, email_service.PAUSED_REASON
    track = email_log.tracker(get_settings().smtp_from_email
                              or get_settings().smtp_username)
    html = (
        '<div style="font-family:system-ui,sans-serif;font-size:15px;'
        'line-height:1.6;white-space:pre-wrap">'
        + body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + "</div>" + track.pixel_html
    )
    try:
        ok = email_service._send_via_smtp(to, subject, html, body,
                                          message_id=track.message_id)
        why = "" if ok else "SMTP reported failure"
    except Exception as e:
        # Returned to the caller (recorded on the request as its delivery
        # error) — and logged here with the traceback.
        logger.warning("message_sender: email to a CSP failed: %s: %s",
                       type(e).__name__, e, exc_info=True)
        ok, why = False, f"{type(e).__name__}: {e}"
    email_log.record(kind=kind, to_email=to, subject=subject, ok=ok,
                     error=why, track=track, csp_id=csp_id, csp_name=csp_name)
    return ok, why


def send_via(channel: MessageChannel, to: str, subject: str, body: str,
             **tracking) -> Tuple[bool, str]:
    """Dispatch on the channel's kind. Returns (sent, why not). `tracking`
    (kind, csp_id, csp_name) is what the email is recorded as (No. 127)."""
    if channel.kind == EMAIL:
        return _send_email(to, subject, body, **tracking)
    if channel.kind == WHATSAPP:
        # WhatsApp needs a Meta-approved template with values filled in, not
        # a finished text; it is sent by whatsapp_platform.send (No. 78).
        return False, (
            "Free-text WhatsApp is not allowed by Meta; send through "
            "whatsapp_platform.send with the stored wording."
        )
    return False, f"No sender exists for a {channel.kind!r} channel."


# ---- asking one CSP for their details ------------------------------------

def address_for(record, channel_kind: str) -> Tuple[str, str]:
    """Where to reach this CSP, and by what. ('', '') when nowhere.

    WhatsApp first when the channel is WhatsApp and the number is usable,
    email otherwise — a CSP with no mobile is still reachable, and falling
    back is better than not asking them at all.
    """
    from app.services.alert_composer import normalize_mobile

    mobile = normalize_mobile(getattr(record, "mobile", "") or "")
    email = (getattr(record, "email", "") or "").strip()

    if channel_kind == WHATSAPP and mobile:
        return mobile, VIA_WHATSAPP
    if email:
        return email, VIA_EMAIL
    if mobile:
        return mobile, VIA_WHATSAPP
    return "", ""


# After a failed ask, the automatic jobs leave that CSP alone this long
# (22 Oct 2026, No. 137). Without it a job running every few minutes tried
# the same CSP on every run while the WhatsApp platform was failing, and
# filled the Messages screen with the same rejection.
RETRY_FAILED_AFTER = timedelta(minutes=30)


def failed_recently(session: Session, csp_id: str) -> Optional[datetime]:
    """When this CSP's last ask failed, if within RETRY_FAILED_AFTER."""
    from app.models.data_request import DataRequest
    since = datetime.now(timezone.utc) - RETRY_FAILED_AFTER
    return session.execute(
        select(DataRequest.created_at).where(
            DataRequest.csp_id == csp_id,
            DataRequest.delivery_error.isnot(None),
            DataRequest.created_at > since,
        ).order_by(DataRequest.created_at.desc())
    ).scalars().first()


@telemetry.traced("ask_csp_for_details", "message_sender")
def ask_for_details(session: Session, record, *,
                    channel: Optional[MessageChannel] = None,
                    template: Optional[MessageTemplate] = None,
                    verify: bool = False,
                    manual: bool = False,
                    allow_email: bool = False,
                    ) -> dict:
    """Send one CSP a link to confirm their own details.

    allow_email (No. 150): the contact loop asks by email a CSP whose
    WhatsApp number did not work, even while CSPs are otherwise asked on
    WhatsApp only (CSP_DATA_REQUESTS_BY_EMAIL off).

    Reuses an open request rather than issuing a second link: being asked
    twice with two different links is confusing, and the first one would
    silently stop working.
    """
    if getattr(record, "send_hold", None):
        # Inactive / not live yet (No. 121): nothing is sent to this CSP.
        return {"csp_id": record.csp_id, "sent": False,
                "reason": record.send_hold}
    if not manual:
        # Someone pressing Send (manual=True) is never held back.
        failed_at = failed_recently(session, record.csp_id)
        if failed_at is not None:
            return {"csp_id": record.csp_id, "sent": False,
                    "reason": "the last try failed; tried again "
                              f"{int(RETRY_FAILED_AFTER.total_seconds() // 60)}"
                              " minutes after it"}
    channel = channel or choose_channel(session)
    template = template or template_for(session, record, verify)

    if (channel.kind != WHATSAPP and not allow_email
            and not get_settings().csp_data_requests_by_email):
        # Decided 11 Oct 2026 (tracker No. 53): CSPs are asked on WhatsApp
        # only. Until WhatsApp sending works, nobody is asked by email; the
        # request simply waits. CSP_DATA_REQUESTS_BY_EMAIL turns email on.
        return {"csp_id": record.csp_id, "sent": False,
                "reason": "waiting for WhatsApp — CSPs are not asked by email"}

    existing = drs.open_request_for(session, record.csp_id)
    if existing is not None and existing.sent_to:
        return {"csp_id": record.csp_id, "sent": False,
                "reason": "already asked and waiting for a reply"}

    # Zoho first (No. 124): what Eko's team typed into the CSP's Zoho Lead
    # is filled in, and the CSP is asked only for what is still missing.
    if drs.fields_to_ask(record):
        from app.services import zoho_fill
        filled = zoho_fill.fill_from_zoho(session, record)
        if filled:
            session.commit()

    fields = drs.fields_to_ask(record)
    if not fields and not verify:
        return {"csp_id": record.csp_id, "sent": False,
                "reason": "nothing is missing from their own details"}
    # verify=True (No. 126): an old CSP checks their whole record even when
    # nothing is blank — a wrong value on file is still worth catching.

    if (not verify and not manual and fields
            and set(fields) <= set(fo.ASKED_FROM_CSP_WHEN_BLANK)
            and drs.answered_count(session, record.csp_id) >= 2):
        # No. 143: AO / RBO Name INFO could not map are asked in the
        # "details still needed" message after the first form — once. Still
        # blank after that, they are the RM's (No. 140: "don't WhatsApp
        # twice if only AO is left"); the missing-data alert asks them.
        return {"csp_id": record.csp_id, "sent": False,
                "reason": "only AO / RBO Name is still blank after the "
                          "CSP was asked for it — not asked again; their "
                          "RM is alerted to fill it"}

    to, via = address_for(record, channel.kind)
    if not to:
        return {"csp_id": record.csp_id, "sent": False,
                "reason": "no usable mobile number and no email address"}

    if existing is not None:
        request, token = existing, None
    else:
        request, token = drs.create(session, record.csp_id,
                                    fo.request_fields(record, verify))

    if token is None:
        # An open request whose link was never delivered. The token cannot
        # be recovered — it was only ever in the link — so a fresh one is
        # issued and the old one closed.
        drs.cancel(session, record.csp_id, "its link was never delivered")
        request, token = drs.create(session, record.csp_id,
                                    fo.request_fields(record, verify))

    link = drs.link_for(token)
    if not link_is_reachable(link):
        # Close the request rather than leaving them "asked" with a link
        # that was never going to work.
        drs.cancel(session, record.csp_id, "the link is not publicly reachable")
        session.commit()
        return {"csp_id": record.csp_id, "sent": False,
                "reason": why_unreachable(link)}

    body = render(template.body, name=getattr(record, "name", "") or
                  record.csp_id, link=link, fields=fields)
    subject = template.subject or "Please confirm your details"

    if via == VIA_WHATSAPP:
        # Through Eko's WhatsApp platform (No. 78): the stored wording is
        # sent as a Meta-approved template with the values filled in.
        from app.services import whatsapp_platform as wa
        from app.services import message_log
        readable = (", ".join(fo.label_of(f) for f in fields)
                    or "all your details")
        kind = (message_log.KIND_MISSING_DATA
                if template.purpose == PURPOSE_MISSING_DATA
                else message_log.KIND_DATA_REQUEST)
        outcome = wa.send(
            to, template.body,
            {"name": getattr(record, "name", "") or record.csp_id,
             "link": link, "fields": readable},
            source_name=message_log.source_name(kind, record.csp_id))
        sent, why = outcome["status"] == wa.SENT, outcome["reason"]
        # Every attempt, sent or not, for the WhatsApp messages screen
        # (No. 110).
        message_log.record(
            session, kind=kind, mobile=to, outcome=outcome,
            csp_id=record.csp_id, csp_name=getattr(record, "name", "") or "",
            data_request_id=request.id)
    else:
        from app.models.email_message import KIND_DETAILS
        sent, why = send_via(channel, to, subject, body, kind=KIND_DETAILS,
                             csp_id=record.csp_id,
                             csp_name=getattr(record, "name", "") or "")

    request.sent_via = via
    request.sent_to = to
    request.delivery_error = None if sent else why
    if not sent:
        # An undelivered ask is not an ask. Close it so the next attempt
        # issues a fresh link rather than pointing at a dead one.
        drs.cancel(session, record.csp_id, "delivery failed")
    channel.last_used_at = datetime.now(timezone.utc)
    channel.last_error = None if sent else why
    session.commit()

    logger.info(
        "message_sender.ask_for_details: CSP %s %s via %s (%s)",
        record.csp_id, "asked" if sent else "NOT asked", via, to,
    )
    return {"csp_id": record.csp_id, "sent": sent, "via": via, "to": to,
            "reason": "" if sent else why}
