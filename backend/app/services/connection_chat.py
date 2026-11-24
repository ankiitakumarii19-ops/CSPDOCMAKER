"""
CSP DocMaker — connecting by chat (PROJECT-REGISTER No. 210, ZU-03)

  "set csp sheet to https://docs.google.com/spreadsheets/d/…"  -> Do it card
  "set mail server to smtp.gmail.com"                          -> Do it card
  "test my sheet" / "test email" / "test connections"          -> runs the test(s)
  "set smtp password to …"                                     -> refused: passwords
                                                                  only in the locked box

Fixed words (connection_catalog.words), no AI. A password or key is never
taken in the chat — the chat would keep it in its history; the Connections
screen's box sends it straight to the locked store.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from app.services import connection_catalog as catalog

SET = re.compile(r"^\s*(?:please\s+)?(?:set|change|connect|use|put|update)\s+"
                 r"(?:the\s+|my\s+)?(?P<what>.+?)\s+(?:to|=|as)\s+"
                 r"(?P<value>\S.*?)\s*[.!?]*\s*$", re.I)
TEST = re.compile(r"^\s*(?:please\s+)?(?:test|check)\s+(?:the\s+|my\s+)?"
                  r"(?P<what>connections?|sheets?|google sheets?|email|mail|"
                  r"whatsapp|crm|zoho)(?:\s+connections?)?\s*[.!?]*\s*$",
                  re.I)
SECRET_WORDS = re.compile(r"\b(password|passcode|secret|token|api key|"
                          r"app password)\b", re.I)


@dataclass
class Parsed:
    connection: Optional[catalog.Connection] = None
    value: object = None
    tests: Optional[List[str]] = None
    problem: Optional[str] = None


def find(text: str) -> List[catalog.Connection]:
    t = " " + " ".join(text.lower().split()) + " "
    hits = []
    for c in catalog.CONNECTIONS:
        best = max([len(w) for w in c.words + (c.label.lower(),)
                    if f" {w} " in t] or [0])
        if best:
            hits.append((best, c))
    if not hits:
        return []
    top = max(b for b, _ in hits)
    return [c for b, c in hits if b == top]


def parse(question: str) -> Optional[Parsed]:
    m = TEST.match(question or "")
    if m:
        w = m.group("what").lower()
        group = ("sheets" if "sheet" in w else "email" if "mail" in w else
                 "whatsapp" if "whatsapp" in w else
                 "crm" if w in ("crm", "zoho") else None)
        return Parsed(tests=[group] if group else ["sheets", "whatsapp",
                                                   "crm"])
    m = SET.match(question or "")
    if not m:
        return None
    what = m.group("what")
    if SECRET_WORDS.search(what):
        return Parsed(problem=(
            "Please don't type a password or key in the chat — the chat "
            "keeps what you write. Enter it on Setup → Connections, in its "
            "own box: it is kept locked and never shown again."))
    found = find(what)
    if not found:
        return None
    if len(found) > 1:
        return Parsed(problem="Which one: " + "; ".join(
            f"**{c.label}**" for c in found) + "?")
    c = found[0]
    try:
        return Parsed(connection=c, value=catalog.parse(c, m.group("value")))
    except catalog.ConnectionError_ as e:
        return Parsed(connection=c, problem=str(e))
