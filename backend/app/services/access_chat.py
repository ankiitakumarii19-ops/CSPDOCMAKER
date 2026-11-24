"""
CSP DocMaker — giving or taking a feature by chat (PROJECT-REGISTER No. 206,
ZU-02)

  "give RMs the dashboard"           "take whatsapp messages from admins"
  "give rm.one@eko.co.in replies"    "switch off message by hand for rms"
  "reset dashboard for rms"          (back to today's access)

Fixed rules, no AI: the feature is found by the fixed words in
feature_catalog, the role or person by their name / email. Nothing changes
until the Super Admin presses Do it (workspace_setup.run →
feature_access.set_for_role / set_for_person, via="chat").
"""

import re
from dataclasses import dataclass
from typing import Dict, Optional

from app.services import feature_catalog as catalog

GIVE = re.compile(r"^\s*(?:please\s+|pls\s+)?(?:give|allow|grant|switch on|"
                  r"turn on|enable)\s+(?P<rest>.+?)\s*[.!?]*\s*$", re.I)
TAKE = re.compile(r"^\s*(?:please\s+|pls\s+)?(?:take away|take|remove|"
                  r"switch off|turn off|block|disable)\s+(?P<rest>.+?)"
                  r"\s*[.!?]*\s*$", re.I)
RESET = re.compile(r"^\s*(?:please\s+)?(?:reset|undo access)\s+(?P<rest>.+?)"
                   r"\s*[.!?]*\s*$", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


@dataclass
class Parsed:
    feature: Optional[catalog.Feature] = None
    subject_kind: Optional[str] = None      # "role" | "person"
    subject: Optional[str] = None           # role key or email
    subject_name: Optional[str] = None
    allowed: Optional[bool] = None
    problem: Optional[str] = None


def parse(question: str, own_roles: Dict[str, str] = None) -> Optional[Parsed]:
    """None when the question is not a give / take command that names both
    a feature and a role or person. own_roles: {key: name}."""
    m, value = GIVE.match(question or ""), True
    if not m:
        m, value = TAKE.match(question or ""), False
    if not m:
        m, value = RESET.match(question or ""), None
    if not m:
        return None
    rest = m.group("rest")
    low = " " + " ".join(rest.lower().split()) + " "

    kind = key = name = None
    email = EMAIL.search(rest)
    if email:
        kind, key, name = "person", email.group(0).lower(), email.group(0).lower()
        low = low.replace(key, " ")
    else:
        for k, n in sorted((own_roles or {}).items(),
                           key=lambda kv: -len(kv[1])):
            if f" {n.lower()} " in low or f" {n.lower()}s " in low:
                kind, key, name = "role", k, n
                low = low.replace(n.lower(), " ")
                break
        if kind is None:
            if re.search(r" super ?admins? ", low):
                return Parsed(problem="A Super Admin always keeps every "
                                      "feature.")
            if re.search(r" (rms?|relationship managers?) ", low):
                kind, key, name = "role", "rm", "RMs"
                low = re.sub(r" (rms?|relationship managers?) ", " ", low)
            elif re.search(r" admins? ", low):
                kind, key, name = "role", "admin", "Admins"
                low = re.sub(r" admins? ", " ", low)
    if kind is None:
        return None
    found = catalog.find(low)
    if not found:
        return None
    if len(found) > 1:
        return Parsed(problem="Which feature: " + "; ".join(
            f"**{f.title}**" for f in found) + "?")
    return Parsed(feature=found[0], subject_kind=kind, subject=key,
                  subject_name=name, allowed=value)
