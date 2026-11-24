"""
CSP DocMaker — is this CSP a KO or a Sub-KO?

Confirmed 11 Oct 2026 (tracker No. 57). A KO's CSP code has 8 characters
(e.g. 1A850344). A Sub-KO's code is its KO's code plus one or two more
characters — 9 or 10 in all (1A8503447, 1A85034408).

The length of the code decides everything that differs between them:

  * which tab of the CSP spreadsheet the row lives in (KOData / SUBKOData);
  * the Training Certificate's wording — "KO Code" or "Sub-KO Code";
  * the BCP, which is made for a KO only, never for a Sub-KO.

A code of any other length is neither. It is reported, never guessed: the
Training Certificate keeps its general "KO/Sub-KO" wording for it.
"""

from typing import Iterable, List, Optional

KO = "ko"
SUB_KO = "sub_ko"

KO_LENGTH = 8
SUB_KO_LENGTHS = (9, 10)

# The Training Certificate's wording, replaced once the level is known.
TOKEN = "KO/Sub-KO"
LABELS = {KO: "KO", SUB_KO: "Sub-KO"}


def _lengths(text: str) -> tuple:
    return tuple(int(p) for p in str(text or "").split(",")
                 if p.strip().isdigit())


def level_of(code: Optional[str]) -> Optional[str]:
    """KO, SUB_KO, or None when the code is neither length.

    No. 211: each workspace sets its own rule (Settings → Records and
    words): two types by code length — Eko's 8 / 9-10, the defaults — or
    one type for every record."""
    from app.config import get_settings
    s = get_settings()
    code = (code or "").strip()
    if s.record_type_rule == "one_type":
        return KO if code else None
    length = len(code)
    if length in _lengths(s.record_main_lengths):
        return KO
    if length in _lengths(s.record_second_lengths):
        return SUB_KO
    return None


def label_for(code: Optional[str]) -> str:
    """'KO' or 'Sub-KO' for the certificate (the workspace's own words,
    No. 211), or '' when unknown."""
    from app.config import get_settings
    s = get_settings()
    level = level_of(code)
    if level == KO:
        return s.word_main_type
    if level == SUB_KO:
        return s.word_second_type
    return ""


def parent_ko_code(code: Optional[str]) -> Optional[str]:
    """The KO a Sub-KO belongs to: its first 8 characters."""
    code = (code or "").strip()
    if level_of(code) != SUB_KO:
        return None
    from app.config import get_settings
    main = _lengths(get_settings().record_main_lengths)
    return code[:min(main)] if main else None


def allowed_documents(code: Optional[str], document_types: Iterable) -> List:
    """The requested documents this CSP may receive.

    The BCP is for a KO only. A Sub-KO never gets one, whoever asks.
    """
    from app.models.enums import DocumentType

    wanted = list(document_types)
    if level_of(code) == SUB_KO:
        # No. 212: the workspace's own list (Eko: BCP).
        from app.config import get_settings
        never = {c.strip().upper() for c in str(
            get_settings().documents_not_for_second_type or "").split(",")
            if c.strip()}
        return [d for d in wanted
                if str(getattr(d, "value", d)).upper() not in never]
    return wanted
