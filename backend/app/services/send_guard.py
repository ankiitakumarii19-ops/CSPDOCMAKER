"""
CSP DocMaker — may anything be sent now, and to whom (PROJECT-REGISTER
No. 215, Stage 8: TK-066, TK-067)

Three switches per workspace (Setup → Setup guide; also Settings → Going
live), checked where every WhatsApp and every email (except sign-in codes)
goes out — whatsapp_platform.send and email_service.paused():

  pause_all       nothing is sent at all, by the app or a person;
  workspace_live  off = the workspace is still being set up: nothing goes to
                  real people. Eko's workspace is live; a new workspace
                  starts NOT live and goes live from the Setup guide, which
                  first checks the setup is complete;
  test_mode       everything goes ONLY to the Super Admin's own number /
                  email (test_mode_phone / test_mode_email), marked as a
                  test, so the whole flow can be tried before going live.
"""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _s():
    from app.config import get_settings
    return get_settings()


def refusal() -> Optional[str]:
    """Why nothing may be sent now, or None."""
    s = _s()
    if s.pause_all:
        return ("everything is paused for this workspace (Setup → Setup "
                "guide → Pause all)")
    if s.test_mode:
        return None
    if not s.workspace_live:
        return ("this workspace is not live yet — nothing goes to real "
                "people (Setup → Setup guide: try it in test mode, then go "
                "live)")
    return None


def whatsapp_to(phone: str) -> Tuple[Optional[str], Optional[str]]:
    """(number to send to, refusal). In test mode: the test number."""
    why = refusal()
    if why:
        return None, why
    s = _s()
    if s.test_mode:
        test = (s.test_mode_phone or "").strip()
        if not test:
            return None, ("test mode is on but no test WhatsApp number is "
                          "set (Setup → Setup guide)")
        return test, None
    return phone, None


def email_to(address: str) -> str:
    """The address an email really goes to: the test address in test mode."""
    s = _s()
    if s.test_mode and (s.test_mode_email or "").strip():
        return s.test_mode_email.strip()
    return address


def test_prefix(original: str) -> str:
    """Marks a test message with whom it was really for."""
    return f"[TEST — for {original}] " if _s().test_mode else ""
