"""
CSP DocMaker — the day filter on every list (PROJECT-REGISTER No. 272)

The Admin dashboard's "Today / Yesterday / On a date / From – To" filter
(No. 171), for the other lists too: WhatsApp messages, Emails and the RM
dashboard. Days are India days (Asia/Kolkata), as people at Eko count them;
date_from and date_to are both inclusive, in YYYY-MM-DD form. The same rules
as admin_router._document_days, kept here so every list shares one copy.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

# India time (no daylight saving, so a fixed offset is exact).
IST = timezone(timedelta(hours=5, minutes=30))

Bounds = Tuple[Optional[datetime], Optional[datetime]]


def _parse(value: Optional[str], field: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=IST)
    except ValueError:
        raise ValueError(
            f"{field} must be a date in YYYY-MM-DD form, not '{value}'.")


def bounds(date_from: Optional[str], date_to: Optional[str]) -> Bounds:
    """(start, end) of the India days asked — start inclusive, end
    exclusive. (None, None) = every day. ValueError, in plain words, for a
    malformed date or a "to" before the "from"."""
    start = _parse(date_from, "date_from")
    end = _parse(date_to, "date_to")
    if start and end and end < start:
        raise ValueError("date_to cannot be before date_from.")
    return start, (end + timedelta(days=1)) if end else None


def http_bounds(date_from: Optional[str], date_to: Optional[str]) -> Bounds:
    """bounds(), with a bad date answered as a 400 (for the routers)."""
    from fastapi import HTTPException, status

    try:
        return bounds(date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def asked(days: Bounds) -> bool:
    return days[0] is not None or days[1] is not None


def within(when, days: Bounds) -> bool:
    """Is this moment (a datetime or an ISO string) on one of the days?
    Nothing asked = always; no moment at all = never, once a day is asked."""
    start, end = days
    if start is None and end is None:
        return True
    if not when:
        return False
    if isinstance(when, str):
        when = datetime.fromisoformat(when)
    if when.tzinfo is None:          # stored times are UTC
        when = when.replace(tzinfo=timezone.utc)
    if start is not None and when < start:
        return False
    if end is not None and when >= end:
        return False
    return True


def where(query, column, days: Bounds):
    """The query, kept to rows whose `column` falls on the days asked."""
    start, end = days
    if start is not None:
        query = query.where(column >= start)
    if end is not None:
        query = query.where(column < end)
    return query
