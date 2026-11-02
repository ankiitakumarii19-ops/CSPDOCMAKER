"""
CSP DocMaker — one way of matching a search (No. 175)

Every search box finds CSPs the same way: part of a word is enough
("1A8507" finds 1A850725), capitals and extra spaces do not matter, and a
phone number is matched on its digits ("98123 45" finds +91-98123-45670).
Searched: CSP code, name, phone, email, district, state and RM.

The screens' own filtering (lib/searchMatch.ts) follows the same rules.
"""

import re

from sqlalchemy import case, func, or_

from app.models.csp_record import CSPRecord

FIELDS = ("csp_id", "csp_code", "name", "email", "district", "state", "rm_name")


def normalize(text: str) -> str:
    """Lower case, spaces collapsed, ends trimmed."""
    return " ".join((text or "").split()).lower()


def _like(term: str) -> str:
    # % and _ typed by a person are letters, not wildcards.
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def csp_condition(q: str):
    """The WHERE for CSPRecord: any field contains the search; None = all."""
    term = normalize(q)
    if not term:
        return None
    like = _like(term)
    parts = [func.regexp_replace(getattr(CSPRecord, f), r"\s+", " ", "g").ilike(like, escape="\\")
             for f in FIELDS]
    digits = re.sub(r"\D", "", term)
    if len(digits) >= 3:
        parts.append(func.regexp_replace(CSPRecord.mobile, r"[^0-9]", "", "g")
                     .ilike(f"%{digits}%"))
    return or_(*parts)


def best_first(q: str):
    """ORDER BY: the exact code, then codes starting with it, then the rest
    by name."""
    term = normalize(q)
    return (case((func.lower(CSPRecord.csp_id) == term, 0),
                 (func.lower(CSPRecord.csp_id).like(f"{term}%"), 1),
                 else_=2),
            CSPRecord.name)
