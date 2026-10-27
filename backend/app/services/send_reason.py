"""
CSP DocMaker — why a message was sent (No. 156)

Asked 27 Oct 2026: show whether a WhatsApp / email went out because an email
bounced, because the CSP asked, to the alternate number because the main one
is not on WhatsApp, or by email because WhatsApp could not reach them.

The part of the app that decides to send says why, around the send:

    with send_reason.because(send_reason.EMAIL_BOUNCED):
        message_sender.ask_for_details(...)

and the record of every WhatsApp (message_log.record) and email
(email_log.record) made inside it carries that reason. A message sent by the
usual flow carries none ("usual flow" on screen).
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

REPLY = "reply"
CSP_ASKED = "csp_asked"
NOT_RECEIVED = "documents_not_received"
EMAIL_BOUNCED = "email_bounced"
WHATSAPP_UNREACHABLE = "whatsapp_unreachable"
ALTERNATE_NUMBER = "alternate_number"
CORRECTED = "contact_corrected"

LABELS = {
    REPLY: "Reply to the CSP's message",
    CSP_ASKED: "The CSP asked (new link / change details)",
    NOT_RECEIVED: "CSP said the documents did not arrive",
    EMAIL_BOUNCED: "Their email bounced",
    WHATSAPP_UNREACHABLE: "WhatsApp did not reach them",
    ALTERNATE_NUMBER: "Alternate number (main one unreachable)",
    CORRECTED: "Sent again after their number / email was corrected",
}
USUAL = "Usual flow"

_current: ContextVar[Optional[str]] = ContextVar("send_reason", default=None)


def current() -> Optional[str]:
    return _current.get()


def label(reason: Optional[str]) -> str:
    return LABELS.get(reason or "", USUAL)


@contextmanager
def because(reason: str):
    token = _current.set(reason)
    try:
        yield
    finally:
        _current.reset(token)
