"""
CSP DocMaker — RM Resolution

Decides which RM a CSP belongs to. This is the basis of access control, so it
never guesses: a CSP it cannot resolve confidently is marked 'unresolved',
which means no RM can reach it and an Admin has to fix the sheet.

Confirmed rules:

  1. The CSP row names an RM  → that RM.
  2. The RM cell is empty     → the INFO tab's RM for the CSP's LHO, then for
     its State. INFO states directly who covers what, so it is preferred over
     inferring the map from whichever rows happen to name an RM.
  3. Still nothing, or the answer is ambiguous → 'unresolved', which every RM
     is alerted about and may act on, so no CSP is stranded.

An RM is matched to a login email through the authorization sheet
(authorization_records). INFO carries the email directly, so INFO matches on
email; only the CSP row's RM column has to be matched by name. That matters
because the two sheets spell people differently — INFO says "Vandana Kumar"
where the authorization sheet says "Vandana".

Being named in INFO grants nothing. The authorization sheet is the only thing
that decides who may sign in, so a CSP pointing at someone who cannot log in
is 'unresolved' (and therefore visible to every RM) rather than locked away.
"""

import logging
from collections import defaultdict
from typing import Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

# How rm_email was decided.
BY_SHEET = "sheet"
BY_LHO = "lho"
BY_INFO_LHO = "info_lho"
BY_INFO_STATE = "info_state"
UNRESOLVED = "unresolved"


def normalize_name(name: Optional[str]) -> str:
    """Compare names ignoring case, punctuation spacing and repeated spaces."""
    return " ".join((name or "").split()).strip().lower()


def build_name_to_email(rm_records: Iterable) -> Dict[str, str]:
    """RM name → login email, from the authorization records.

    A name held by more than one authorized RM is dropped: it cannot identify
    one person, and guessing would hand one RM another RM's CSPs.
    """
    by_name: Dict[str, set] = defaultdict(set)
    for record in rm_records:
        key = normalize_name(getattr(record, "name", None))
        email = (getattr(record, "email", None) or "").strip().lower()
        if key and email:
            by_name[key].add(email)

    resolved = {}
    for name, emails in by_name.items():
        if len(emails) == 1:
            resolved[name] = next(iter(emails))
        else:
            logger.warning(
                "rm_resolution: RM name %r is used by %d authorized accounts — "
                "CSPs naming it cannot be resolved", name, len(emails),
            )
    return resolved


def build_lho_to_name(rows: Iterable[Dict[str, str]]) -> Dict[str, str]:
    """LHO → RM name, learned from the sheet rows that name an RM.

    One LHO has exactly one RM. If rows disagree about an LHO, that LHO is
    dropped so the conflict surfaces as 'unresolved' rather than a silent pick.
    """
    by_lho: Dict[str, set] = defaultdict(set)
    for row in rows:
        lho = normalize_name(row.get("lho"))
        rm_name = normalize_name(row.get("rm_name"))
        if lho and rm_name:
            by_lho[lho].add(rm_name)

    resolved = {}
    for lho, names in by_lho.items():
        if len(names) == 1:
            resolved[lho] = next(iter(names))
        else:
            logger.warning(
                "rm_resolution: LHO %r is claimed by %d different RMs in the sheet "
                "— CSPs in it cannot be resolved", lho, len(names),
            )
    return resolved


def info_rm(row: Dict[str, str], info) -> Tuple[Optional[object], str]:
    """The RM the INFO tab says covers this CSP's territory.

    LHO first, then State. Returns (person, how); (None, UNRESOLVED) when
    INFO has no unique answer.
    """
    if info is None:
        return None, UNRESOLVED

    from app.services.info_directory import RM as INFO_RM

    lho = normalize_name(row.get("lho"))
    state = normalize_name(row.get("state"))

    if lho:
        person = info.find_by_territory(INFO_RM, lho, "")
        if person:
            return person, BY_INFO_LHO
    if state:
        person = info.find_by_territory(INFO_RM, "", state)
        if person:
            return person, BY_INFO_STATE

    return None, UNRESOLVED


def resolve_rm(
    row: Dict[str, str],
    name_to_email: Dict[str, str],
    lho_to_name: Dict[str, str],
    info=None,
    authorized_emails=None,
) -> Tuple[Optional[str], str]:
    """Resolve one CSP row to (rm_email, how).

    Args:
        row: Mapped CSP row (canonical field names).
        name_to_email: From build_name_to_email().
        lho_to_name: From build_lho_to_name() — the fallback used when there
            is no INFO directory to consult.
        info: An InfoDirectory, when the INFO tab could be read.
        authorized_emails: Emails that may sign in as an RM. An INFO match
            outside this set is recorded but grants no access.

    Returns:
        (rm_email or None, one of BY_SHEET / BY_INFO_LHO / BY_INFO_STATE /
         BY_LHO / UNRESOLVED)
    """
    allowed = {e.strip().lower() for e in (authorized_emails or set()) if e}

    sheet_name = normalize_name(row.get("rm_name"))
    if sheet_name:
        email = name_to_email.get(sheet_name)
        if email:
            return email, BY_SHEET
        # Named but not an authorized, uniquely identifiable RM.
        return None, UNRESOLVED

    lho = normalize_name(row.get("lho"))

    if info is not None:
        person, how = info_rm(row, info)
        if person is not None:
            email = (getattr(person, "email", "") or "").strip().lower()
            if email and email in allowed:
                return email, how
            logger.info(
                "rm_resolution: INFO covers this CSP with %r, who is not an "
                "active authorized RM — leaving it unresolved so every RM is "
                "alerted", person.name,
            )
            return None, UNRESOLVED

    # No INFO directory available: fall back to the map learned from the rows.
    if lho:
        lho_name = lho_to_name.get(lho)
        if lho_name:
            email = name_to_email.get(lho_name)
            if email:
                return email, BY_LHO

    return None, UNRESOLVED
