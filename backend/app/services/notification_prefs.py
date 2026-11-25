"""
CSP DocMaker — what each person is told, and how (No. 240, SaaS upgrade Stage 3)

The notifications the app sends to STAFF (never to CSPs: their messages are
the workspace's rules, untouched). Each one lists the channels it really goes
by. A person may switch off an optional one for themselves; a mandatory one
(sign-in codes, failure alerts, the Action Required bell) cannot be switched
off — the brief: "without overriding mandatory operational notifications or
compliance alerts".

SMS and WhatsApp are not used for staff messages in this app; the screen says
so rather than offering a switch that would do nothing.

Stored in user_preferences.notifications as {kind: {channel: false}} — only
what was switched off. Nothing stored = everything as before.

`keep_wanted(session, kind, emails)` is called where those emails are
addressed (weekly_health.recipients, contact_report.recipients).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

logger = logging.getLogger(__name__)

CHANNELS = (("in_app", "In the app"), ("email", "Email"),
            ("whatsapp", "WhatsApp"), ("sms", "SMS"))
NOT_FOR_STAFF = {"whatsapp": "Not used for staff messages in this app.",
                 "sms": "No SMS service is connected to this app."}


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    about: str
    channels: tuple          # the channels it really goes by
    mandatory: bool
    why_mandatory: str = ""
    who: str = ""            # who gets it at all


KINDS: tuple[Kind, ...] = (
    Kind("sign_in_codes", "Sign-in codes", "The code emailed when you sign in "
         "or reset your password.", ("email",), True,
         "Needed to sign in.", "Everyone"),
    Kind("failure_alerts", "Something keeps failing",
         "A sheet read stuck, an agent failing, WhatsApps failing, the backup "
         "missing.", ("email",), True,
         "A compliance alert: someone must always hear about it.",
         "The Super Admins (or Settings -> Alerts)"),
    Kind("action_required", "Action Required",
         "The bell: CSPs with details still missing.", ("in_app",), True,
         "Operational work list.", "RMs, Admins, Super Admins"),
    Kind("weekly_health", "Weekly health email",
         "The week's numbers and what to fix in the setup.", ("email",), False,
         who="The Super Admins (or Settings -> Weekly email: to)"),
    Kind("daily_contact", "Daily contact email",
         "How many messages went today and who could not be reached.",
         ("email",), False,
         who="The Super Admins (or Settings -> Daily contact email: to)"),
)
BY_KEY = {k.key: k for k in KINDS}


class NotificationError(ValueError):
    """A choice that cannot be saved; the message says why."""


def view(saved: Dict[str, Any] | None) -> List[dict]:
    """Every kind, each channel's state for this person."""
    saved = saved or {}
    out = []
    for k in KINDS:
        channels = []
        for ch, name in CHANNELS:
            if ch not in k.channels:
                channels.append({"key": ch, "name": name, "available": False,
                                 "why": NOT_FOR_STAFF.get(ch, "Not sent this way.")})
                continue
            off = (saved.get(k.key) or {}).get(ch) is False
            channels.append({"key": ch, "name": name, "available": True,
                             "on": k.mandatory or not off,
                             "locked": k.mandatory})
        out.append({"key": k.key, "label": k.label, "about": k.about,
                    "mandatory": k.mandatory, "why_mandatory": k.why_mandatory,
                    "who": k.who, "channels": channels})
    return out


def check(raw: Any) -> Dict[str, Dict[str, bool]]:
    """{kind: {channel: bool}} -> what to store (only what is off)."""
    if not isinstance(raw, dict):
        raise NotificationError("Send the choices as {kind: {channel: on/off}}.")
    clean: Dict[str, Dict[str, bool]] = {}
    for key, channels in raw.items():
        kind = BY_KEY.get(key)
        if kind is None:
            raise NotificationError(f"'{key}' is not a notification of this app.")
        if not isinstance(channels, dict):
            raise NotificationError(f"{kind.label}: send each channel as on or off.")
        for ch, on in channels.items():
            if ch not in kind.channels:
                raise NotificationError(f"{kind.label} is not sent by {ch}.")
            if not isinstance(on, bool):
                raise NotificationError(f"{kind.label}: {ch} must be on or off.")
            if not on and kind.mandatory:
                raise NotificationError(f"{kind.label} cannot be switched off: "
                                        f"{kind.why_mandatory}")
            if not on:
                clean.setdefault(key, {})[ch] = False
    return clean


def keep_wanted(session, kind: str, emails: Sequence[str],
                channel: str = "email") -> List[str]:
    """The addresses minus people who switched this off for themselves.
    A mandatory kind is never filtered. A failure to read the choices keeps
    everyone (and is logged): a missed opt-out is better than a lost alert."""
    k = BY_KEY.get(kind)
    emails = list(emails)
    if k is None or k.mandatory or not emails:
        return emails
    from sqlalchemy import select
    from app.models.user_preference import UserPreference
    lower = {e.strip().lower(): e for e in emails}
    try:
        rows = session.execute(select(UserPreference.email, UserPreference.notifications)
                               .where(UserPreference.email.in_(list(lower)))).all()
    except Exception as e:
        logger.error("notification_prefs.keep_wanted: could not read people's "
                     "choices for %s (%s: %s) — sending to everyone listed",
                     kind, type(e).__name__, e)
        return emails
    off = {email for email, prefs in rows
           if ((prefs or {}).get(kind) or {}).get(channel) is False}
    if off:
        logger.info("notification_prefs: %s not sent to %d person(s) who "
                    "switched it off", kind, len(off))
    return [orig for low, orig in lower.items() if low not in off]
