"""
CSP DocMaker — changing a setting by chat (PROJECT-REGISTER No. 204, ZU-01)

"set feedback delay to 30 minutes", "change messages stop at to 7 pm",
"set time zone to 5:30", "set pause emails to on".

Fixed rules, no AI (No. 116): the setting is found by the fixed words in
services/settings_catalog.py; the value is read the same way every time.
The chat never changes anything itself — it shows a card with the value now
and the new value, and the change happens only when the Super Admin presses
Do it (workspace_setup.run → workspace_settings.set_value, via="chat"), with
the same checks and history as the Settings screen.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from app.services import settings_catalog as catalog
from app.services.settings_catalog import SettingError

COMMAND = re.compile(
    r"^\s*(?:please\s+|pls\s+)?(?:set|change|make|put|update)\s+(?:the\s+|my\s+)?"
    r"(?P<what>.+?)\s+(?:to|=|as)\s+(?P<value>[^\n]+?)\s*[.!?]*\s*$", re.I)


@dataclass
class Parsed:
    """What a chat command asks for: one setting and its new value, or the
    settings it could mean, or why it cannot be done."""
    setting: Optional[catalog.Setting] = None
    value: object = None
    choices: Optional[List[catalog.Setting]] = None
    problem: Optional[str] = None


def is_command(question: str) -> bool:
    m = COMMAND.match(question or "")
    return bool(m) and not m.group("what").lower().startswith("up ")


def read_value(setting: catalog.Setting, text: str):
    """The value as typed in the chat -> the setting's value (SettingError
    when it does not fit)."""
    t = (text or "").strip().strip("\"'“”‘’").strip()
    if setting.kind == catalog.INT:
        m = re.search(r"-?\d+", t)
        if not m:
            raise SettingError(f"{setting.label}: give a number"
                               + (f" ({setting.unit})" if setting.unit else "")
                               + ".")
        n = int(m.group(0))
        if setting.unit == "o'clock":
            low = t.lower()
            if re.search(r"\bpm\b|p\.m\.|\bshaam\b|\braat\b", low) and n < 12:
                n += 12
            elif re.search(r"\bam\b|a\.m\.", low) and n == 12:
                n = 0
        return catalog.parse(setting, n)
    if setting.kind == catalog.CHOICE and setting.key == "send_time_zone":
        m = re.fullmatch(r"(?:utc|gmt)?\s*([+-])?\s*(\d{1,2})(?::?(\d{2}))?",
                         t.lower())
        if m:
            t = f"{m.group(1) or '+'}{int(m.group(2)):02d}:{m.group(3) or '00'}"
        return catalog.parse(setting, t)
    return catalog.parse(setting, t)


def parse(question: str) -> Optional[Parsed]:
    """None when the question is not a 'set … to …' command."""
    if not is_command(question):
        return None
    m = COMMAND.match(question)
    what, value = m.group("what"), m.group("value")
    found = catalog.find(what)
    if not found:
        return Parsed(problem=(
            f"I don't know a setting called “{what.strip()}”. Every setting "
            "is on Setup → Settings — use the name shown there."))
    if len(found) > 1:
        return Parsed(choices=found)
    setting = found[0]
    try:
        return Parsed(setting=setting, value=read_value(setting, value))
    except SettingError as e:
        return Parsed(setting=setting, problem=str(e))
