"""
CSP DocMaker — "your documents have been emailed", on WhatsApp

Decided 12 Oct 2026 (tracker No. 78): after a CSP's documents are emailed,
they are also sent a WhatsApp notice. Sent through Eko's WhatsApp platform
(whatsapp_platform.py).

Changed 22 Oct 2026 (No. 135, asked): the documents are NOT sent on WhatsApp
any more. The notice only tells the CSP that their documents were emailed,
and to which address. The private PDF link below is no longer put in new
messages; it is kept so links already sent keep working for their 7 days.
What it was:

  * signed with the app's secret, so it cannot be guessed or altered;
  * good for 7 days, then refused;
  * opens only the PDFs of that one delivery (one processing job), merged
    into a single PDF, so the CSP gets one tidy attachment.

Guards, in order — any one failing means no WhatsApp, and the email that
already went is unaffected:

  * the CSP is not on hold;
  * an active WhatsApp channel (provider eko_wabs) is configured;
  * the app is on a public address (PUBLIC_APP_URL is not localhost) — so
    a laptop copy of the app never messages a CSP;
  * the CSP has a usable mobile number.

Never raises: a WhatsApp problem must not undo or fail a delivery that the
email already completed.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from app import telemetry

logger = logging.getLogger(__name__)

LINK_DAYS = 7
TOKEN_TYPE = "documents-link"

# The wording. Kept stable on purpose: Meta approves a wording once, and the
# platform reuses that approval as long as the text does not change.
#
# Changed 22 Oct 2026 (No. 135): no PDF, so no Document header — a plain
# Utility template (deploy/WHATSAPP-DOCUMENTS-TEMPLATE.md). The platform
# submits a new wording to Meta on its first send; it must then stay exactly
# as approved, character for character.
BODY = (
    "Namaste {name}, your CSP documents ({documents}) have been issued and "
    "sent to your email {email}. Please check your inbox, and the Spam "
    "folder too.\n\n"
    "नमस्ते {name}, आपके CSP दस्तावेज़ ({documents}) जारी कर दिए गए हैं और "
    "आपके ईमेल {email} पर भेज दिए गए हैं। कृपया अपना इनबॉक्स और Spam फ़ोल्डर "
    "भी देखें।\n\n"
    "Namaste {name}, aapke CSP documents ({documents}) jaari kar diye gaye "
    "hain aur aapke email {email} par bhej diye gaye hain. Kripya apna inbox "
    "aur Spam folder bhi dekhein.\n\n"
    "— Team Eko"
)


def link_for(workspace_id, processing_job_id, csp_id: str) -> str:
    """The private download link for one delivery's PDFs."""
    from jose import jwt

    from app.config import get_settings

    s = get_settings()
    claims = {
        "type": TOKEN_TYPE,
        "ws": str(workspace_id),
        "job": str(processing_job_id),
        "csp": csp_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=LINK_DAYS),
    }
    token = jwt.encode(claims, s.jwt_secret_key, algorithm=s.jwt_algorithm)
    return f"{s.public_app_url.rstrip('/')}/api/public/documents/{token}"


def read_link(token: str) -> Optional[dict]:
    """The link's claims if it is genuine and unexpired, else None."""
    from app.services import jwt_service
    claims = jwt_service.decode_token(token)
    if not claims or claims.get("type") != TOKEN_TYPE:
        return None
    return claims


def whatsapp_channel(session):
    """The active WhatsApp channel of this workspace, or None."""
    from sqlalchemy import select

    from app.models.messaging import (
        PROVIDER_EKO_WABS, WHATSAPP, MessageChannel,
    )
    return session.execute(
        select(MessageChannel).where(
            MessageChannel.kind == WHATSAPP,
            MessageChannel.provider == PROVIDER_EKO_WABS,
            MessageChannel.active.is_(True))
    ).scalars().first()


@telemetry.traced("whatsapp_documents_ready", "documents_whatsapp")
def notify(session, csp, job, document_names: List[str],
           mobile: str = None) -> dict:
    """Tell the CSP on WhatsApp that their documents were emailed (no
    PDF on WhatsApp — No. 135). `mobile`: a number other than the record's
    — the CSP's alternate, when the main one is unreachable (No. 152)."""
    from app.services import message_log, message_sender
    from app.services import whatsapp_platform as wa

    try:
        if getattr(csp, "send_hold", None):
            return _skip(csp, csp.send_hold)        # No. 121
        channel = whatsapp_channel(session)
        if channel is None:
            return _skip(csp, "no active WhatsApp channel")
        from app.config import get_settings
        if not message_sender.link_is_reachable(
                get_settings().public_app_url):
            return _skip(csp, "the app is not on a public address "
                              "(PUBLIC_APP_URL) — a laptop copy never "
                              "messages a CSP")
        number = mobile or csp.mobile or ""
        if not wa.phone_for_whatsapp(number):
            return _skip(csp, "no usable mobile number")

        outcome = wa.send(
            number, BODY,
            {"name": csp.name or csp.csp_id,
             "documents": ", ".join(document_names),
             "email": csp.email or "your email"},
            source_name=message_log.source_name(
                message_log.KIND_DOCUMENTS_READY, csp.csp_id))
        # For the WhatsApp messages screen (No. 110).
        message_log.record(
            session, kind=message_log.KIND_DOCUMENTS_READY,
            mobile=number, outcome=outcome, csp_id=csp.csp_id,
            csp_name=csp.name, processing_job_id=job.id)
        channel.last_used_at = datetime.now(timezone.utc)
        channel.last_error = (None if outcome["status"] == wa.SENT
                              else outcome["reason"][:2000])
        session.commit()
        logger.info("documents_whatsapp: CSP %s — %s %s", csp.csp_id,
                    outcome["status"], outcome["reason"])
        return outcome
    except Exception as e:      # never fail a delivery the email completed
        logger.error("documents_whatsapp: CSP %s — %s: %s",
                     getattr(csp, "csp_id", "?"), type(e).__name__, e)
        return {"status": "failed", "reason": f"{type(e).__name__}: {e}"}


def _skip(csp, why: str) -> dict:
    logger.info("documents_whatsapp: CSP %s — not sent: %s", csp.csp_id, why)
    return {"status": "skipped", "reason": why}


def merged_pdf(pdfs: List[bytes]) -> bytes:
    """One PDF made of several, in the order given."""
    import pymupdf

    out = pymupdf.open()
    for data in pdfs:
        with pymupdf.open(stream=data, filetype="pdf") as part:
            out.insert_pdf(part)
    try:
        return out.tobytes()
    finally:
        out.close()
