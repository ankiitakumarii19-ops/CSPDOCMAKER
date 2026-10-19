"""
CSP DocMaker — each workspace's own rules (tracker No. 120)

Asked for 19 Oct 2026: "in my workspace only @eko.co.in works — I want other
workspace owners to choose and add rules according to them." Decided the
same day: anyone may CREATE a workspace with any email; inside it, its Owner
sets:

  * allowed_email_domains — who may be added to, and sign in to, the
    workspace ([] = any address). Enforced where every sign-in and request
    finds its membership (workspace_service.memberships), so a person whose
    address the workspace no longer allows cannot enter it, even if they
    were added before.
  * session_hours        — how long a sign-in to this workspace lasts.
  * members_added_by     — "owner" (default) or "owner_and_admins".
  * message_signoff      — the "— …" line messages to CSPs end with.

Kept in Workspace.settings (JSON). A rule never set falls back to the
server's setting, so Eko's workspace behaves exactly as before until its
Owner changes something.
"""

import re
from typing import List, Optional

from app.config import get_settings

OWNER_ONLY = "owner"
OWNER_AND_ADMINS = "owner_and_admins"
MEMBERS_ADDED_BY = (OWNER_ONLY, OWNER_AND_ADMINS)
MIN_SESSION_HOURS, MAX_SESSION_HOURS = 1, 720
_DOMAIN = re.compile(r"^(?=.{3,253}$)([a-z0-9-]+\.)+[a-z]{2,}$")


class RuleError(ValueError):
    """A rule that cannot be saved; the text says why."""


def _settings(ws) -> dict:
    return dict(getattr(ws, "settings", None) or {})


def clean_domains(values) -> List[str]:
    """['@Eko.co.in ', 'abc.com'] -> ['eko.co.in', 'abc.com'], or RuleError."""
    out = []
    for raw in values or []:
        d = str(raw).strip().lower().lstrip("@")
        if not d:
            continue
        if not _DOMAIN.match(d):
            raise RuleError(f"{raw!r} is not an email domain (like abc.com).")
        if d not in out:
            out.append(d)
    return out


def allowed_domains(ws) -> List[str]:
    s = _settings(ws)
    if "allowed_email_domains" in s:
        return list(s["allowed_email_domains"] or [])
    return list(get_settings().allowed_email_domains)


def email_allowed(ws, email: str) -> bool:
    domains = allowed_domains(ws)
    address = (email or "").strip().lower()
    return not domains or address.endswith(tuple(f"@{d}" for d in domains))


def domains_text(ws) -> str:
    domains = [f"@{d}" for d in allowed_domains(ws)]
    if not domains:
        return "any"
    if len(domains) == 1:
        return domains[0]
    return ", ".join(domains[:-1]) + " or " + domains[-1]


def session_hours(ws) -> int:
    value = _settings(ws).get("session_hours")
    return int(value) if value else get_settings().session_hours


def members_added_by(ws) -> str:
    value = _settings(ws).get("members_added_by")
    return value if value in MEMBERS_ADDED_BY else OWNER_ONLY


def signoff(ws) -> Optional[str]:
    """The sign-off the Owner chose, or None (messages keep their own)."""
    value = (_settings(ws).get("message_signoff") or "").strip()
    return value or None


def describe(ws) -> dict:
    s = _settings(ws)
    return {
        "allowed_email_domains": allowed_domains(ws),
        "allowed_email_domains_set": "allowed_email_domains" in s,
        "session_hours": session_hours(ws),
        "members_added_by": members_added_by(ws),
        "message_signoff": signoff(ws) or "",
        "server_defaults": {
            "allowed_email_domains": list(get_settings().allowed_email_domains),
            "session_hours": get_settings().session_hours,
        },
    }


def starting_rules(owner_email: str) -> dict:
    """A new workspace starts allowing its Owner's own domain."""
    domain = (owner_email or "").strip().lower().split("@")[-1]
    return {"allowed_email_domains": [domain] if domain else []}


def validated(body: dict, super_admin_emails: List[str]) -> dict:
    """The rules to store, or RuleError. A rule that would lock out one of
    the workspace's own Super Admins is refused — the Owner could never
    get back in to undo it."""
    domains = clean_domains(body.get("allowed_email_domains") or [])
    probe = type("W", (), {"settings": {"allowed_email_domains": domains}})()
    shut_out = [e for e in super_admin_emails if not email_allowed(probe, e)]
    if shut_out:
        raise RuleError(
            "These domains would lock out this workspace's Super Admin(s): "
            + ", ".join(shut_out) + ". Add their domain too.")
    try:
        hours = int(body.get("session_hours"))
    except (TypeError, ValueError):
        raise RuleError("Sign-in length must be a whole number of hours.")
    if not MIN_SESSION_HOURS <= hours <= MAX_SESSION_HOURS:
        raise RuleError(f"Sign-in length must be between {MIN_SESSION_HOURS} "
                        f"and {MAX_SESSION_HOURS} hours.")
    added_by = body.get("members_added_by") or OWNER_ONLY
    if added_by not in MEMBERS_ADDED_BY:
        raise RuleError("Choose who can add members: the Owner only, or the "
                        "Owner and Admins.")
    sign = (body.get("message_signoff") or "").strip()
    if len(sign) > 100:
        raise RuleError("The sign-off must be 100 characters or fewer.")
    return {"allowed_email_domains": domains, "session_hours": hours,
            "members_added_by": added_by, "message_signoff": sign}


def resign(body: str, new: str) -> Optional[str]:
    """The message with its last "— …" line changed to "— new", or None if
    it has no such line (left as the Owner wrote it)."""
    lines = body.rstrip().split("\n")
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        if line.startswith("— "):
            if line == f"— {new}":
                return None
            lines[i] = f"— {new}"
            return "\n".join(lines)
        return None
    return None
