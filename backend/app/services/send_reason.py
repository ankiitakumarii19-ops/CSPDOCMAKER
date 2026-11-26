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
RETRY = "sent_again_after_error"
MANUAL = "sent_by_a_person"
GUIDE_VIDEO = "guide_video"
GUIDE_VIDEO_LINK = "guide_video_link"

LABELS = {
    REPLY: "Reply to the CSP's message",
    CSP_ASKED: "The CSP asked (new link / change details)",
    NOT_RECEIVED: "CSP said the documents did not arrive",
    EMAIL_BOUNCED: "Their email bounced",
    WHATSAPP_UNREACHABLE: "WhatsApp did not reach them",
    ALTERNATE_NUMBER: "Alternate number (main one unreachable)",
    CORRECTED: "Sent again after their number / email was corrected",
    RETRY: "Sent again after an error (No. 164)",
    MANUAL: "Sent by a person (Messaging / Action Required, No. 174)",
    GUIDE_VIDEO: "How-to-fill-the-form video (No. 209)",
    GUIDE_VIDEO_LINK: "Verification link sent with the form video (No. 256)",
}
USUAL = "Usual flow"

_current: ContextVar[Optional[str]] = ContextVar("send_reason", default=None)

# No. 194: the person who sent it (their email), for every message a person
# sends — a typed message, the details form / verification link, a reply
# from the Replies screen, an RM's request. None = sent by the app itself.
_person: ContextVar[Optional[str]] = ContextVar("sent_by", default=None)


def current_person() -> Optional[str]:
    return _person.get()


@contextmanager
def sent_by(person: Optional[str]):
    """Every WhatsApp recorded inside carries this person as its sender."""
    token = _person.set((person or "").strip().lower() or None)
    try:
        yield
    finally:
        _person.reset(token)


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
