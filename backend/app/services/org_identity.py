"""
CSP DocMaker — whose name a CSP-facing message carries (No. 247)

Eko's workspace: exactly as always ("Eko Bharat Ventures Pvt Ltd",
"— Team Eko", the Eko logo). Every other workspace: its own name, so a new
organisation's CSPs never see Eko's name on a message.

The WhatsApp wordings are approved by Meta character for character; Eko's are
returned unchanged, and another workspace's differ only by its name (its own
WhatsApp account submits its own wording on the first send).
"""

from __future__ import annotations

EKO_NAME = "Eko Bharat Ventures Pvt Ltd"
EKO_SHORT = "Eko Bharat Ventures"
EKO_TEAM = "Team Eko"


def is_eko() -> bool:
    """Eko's workspace, or no workspace in force (scripts, older callers)."""
    from app.services.workspace_settings import EKO_WORKSPACE
    from app.workspace_context import current_workspace_id
    ws = current_workspace_id()
    return ws is None or str(ws) == str(EKO_WORKSPACE)


def organisation_name() -> str:
    """The organisation a CSP's documents and messages come from."""
    if is_eko():
        return EKO_NAME
    from app.services import workspace_files
    return (workspace_files.workspace_name() or "").strip() or "Your organisation"


def short_name() -> str:
    return EKO_SHORT if is_eko() else organisation_name()


def team() -> str:
    """The sign-off under a WhatsApp message."""
    return EKO_TEAM if is_eko() else f"Team {organisation_name()}"


def swap(text: str) -> str:
    """An Eko wording with this workspace's name in place of Eko's.
    Unchanged for Eko."""
    if is_eko() or not text:
        return text
    return (text.replace(EKO_NAME, organisation_name())
                .replace("Eko Bharat Ventures Private Limited", organisation_name())
                .replace(EKO_SHORT, short_name())
                .replace("Eko\nBharat Ventures", short_name())
                .replace(EKO_TEAM, team()))


_HINTS = None


def neutral(text: str) -> str:
    """A setting's help with Eko's own examples taken out, for any workspace
    but Eko's ("The tab with one row per record (Eko: KOData)." -> "The tab
    with one row per record."). Unchanged for Eko."""
    global _HINTS
    if not text or is_eko() or "Eko" not in text:
        return text
    import re
    if _HINTS is None:
        _HINTS = [
            (re.compile(r",\s*Eko's (?:today|value)\b"), ""),
            (re.compile(r"\s*\((?:Eko: |Eko's )[^()]*(?:\([^()]*\)[^()]*)*\)"), ""),
            (re.compile(r"(^|(?<=[.!?])\s+)Eko: [^.]*(?:\.|$)"), r"\1"),
            (re.compile(r"\bEko's\b"), "the standard"),
            (re.compile(r"\bEko\b"), "the standard"),
            (re.compile(r"\s{2,}"), " "),
        ]
    for pattern, new in _HINTS:
        text = pattern.sub(new, text)
    return text.strip()
