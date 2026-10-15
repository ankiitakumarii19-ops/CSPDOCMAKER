"""
CSP DocMaker — "your documents are ready", on WhatsApp, with the PDFs

Decided 12 Oct 2026 (tracker No. 78): after a CSP's documents are emailed,
they are also sent a WhatsApp notice with the documents attached. Sent through
Eko's WhatsApp platform (whatsapp_platform.py).

WhatsApp attaches a document by fetching it from a public web address, so
each delivery gets a private link:

  * signed with the app's secret, so it cannot be guessed or altered;
  * good for 7 days, then refused;
  * opens only the PDFs of that one delivery (one processing job), merged
    into a single PDF, so the CSP gets one tidy attachment.

Guards, in order — any one failing means no WhatsApp, and the email that
already went is unaffected:

  * an active WhatsApp channel (provider eko_wabs) is configured;
  * the app is on a public address (PUBLIC_APP_URL is not localhost) — the
    same rule that stops a dead link reaching a CSP;
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
# Changed 13 Oct 2026 (tracker No. 90): the earlier wording was approved by
# Meta WITHOUT a document header, so a send with the PDF attached was refused
# (#132018). This wording is registered in Eko's WhatsApp console WITH a
# Document header (deploy/WHATSAPP-DOCUMENTS-TEMPLATE.md); it must match that
# template exactly, character for character.
BODY = (
    "Namaste {name}, your CSP documents ({documents}) have been issued. The "
    "PDF is attached to this message and has also been emailed to {email}.\n\n"
    "नमस्ते {name}, आपके CSP दस्तावेज़ ({documents}) जारी कर दिए गए हैं। PDF इस "
    "संदेश के साथ संलग्न है और {email} पर ईमेल भी किया गया है।\n\n"
    "Namaste {name}, aapke CSP documents ({documents}) jaari kar diye gaye "
    "hain. PDF is message ke saath attached hai aur {email} par email bhi "
    "kiya gaya hai.\n\n"
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
def notify(session, csp, job, document_names: List[str]) -> dict:
    """Send the WhatsApp notice for a delivery that was just emailed."""
    from app.services import message_log, message_sender
    from app.services import whatsapp_platform as wa

    try:
        channel = whatsapp_channel(session)
        if channel is None:
            return _skip(csp, "no active WhatsApp channel")
        link = link_for(job.workspace_id, job.id, csp.csp_id)
        if not message_sender.link_is_reachable(link):
            return _skip(csp, "the app is not on a public address yet "
                              "(PUBLIC_APP_URL), so WhatsApp cannot fetch "
                              "the PDF")
        if not wa.phone_for_whatsapp(csp.mobile or ""):
            return _skip(csp, "no usable mobile number")

        outcome = wa.send(
            csp.mobile, BODY,
            {"name": csp.name or csp.csp_id,
             "documents": ", ".join(document_names),
             "email": csp.email or "your email"},
            source_name=message_log.source_name(
                message_log.KIND_DOCUMENTS_READY, csp.csp_id),
            document_url=link)
        # For the WhatsApp messages screen (No. 110).
        message_log.record(
            session, kind=message_log.KIND_DOCUMENTS_READY,
            mobile=csp.mobile, outcome=outcome, csp_id=csp.csp_id,
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
