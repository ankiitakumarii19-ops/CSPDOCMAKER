"""
CSP DocMaker — a record of every sign-in

The Access screen showed one date: the last time somebody signed in. That
answers "is this account in use" and nothing else. It cannot say whether
an RM signs in daily or signed in once in September, and it cannot say
anything at all about an account that was used and then used again — the
second login simply overwrites the first.

So every successful sign-in is written down, into `audit_logs`. That table
was created with the schema, correctly indexed, and had never had a row
written to it. This is the first thing that writes to it, which also means
the audit trail starts being an audit trail rather than an empty promise.

What is recorded is deliberately thin: who, when, and from where. No
token, no OTP, no password, and no attempt to fingerprint anybody — the
question this answers is "when did this person sign in", and anything
beyond that is data held for no stated reason.

Note what it CANNOT do: show history from before it existed. Every login
until now left only `users.last_login_at`, a single overwritten timestamp.
The history starts today, and the screen says so rather than implying the
account was never used.
"""

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)

LOGIN = "login"

# A person's sign-in history, not a server log. Past this, the question is
# a different one and wants a different screen.
MAX_ENTRIES = 200


async def record_login(session: AsyncSession, user: User,
                       address: Optional[str] = None) -> None:
    """Write down that this person signed in.

    Two things here are the result of this having broken login once, and
    both matter more than the feature does.

    **The workspace is taken from the user, not from context.** Every
    scoped row defaults its `workspace_id` from the ambient workspace —
    but signing in is a PRE-AUTHENTICATION endpoint. Nobody is signed in
    yet, so there is no ambient workspace, the default resolved to NULL,
    and the NOT NULL constraint rejected the row. The user being signed in
    is the only thing that knows which workspace this belongs to.

    **The insert is its own savepoint.** The first version caught
    exceptions around `session.add()`, which cannot fail — the database
    only sees the row at COMMIT, which happens later and outside any
    try/except here. So a bad audit row did not fail quietly; it took the
    whole login transaction down with it and returned a 500. Writing it
    inside a nested transaction means a failure rolls back the audit row
    and nothing else.

    Never raises. The person is already authenticated by this point, and
    refusing them because a log row would not write is the worse outcome.
    """
    try:
        async with session.begin_nested():
            session.add(AuditLog(
                # Not from the ambient context: there is none during login.
                workspace_id=user.workspace_id,
                user_id=user.id,
                action=LOGIN,
                resource_type="user",
                resource_id=str(user.id),
                result="success",
                metadata_json={
                    "email": user.email,
                    "role": getattr(user.role, "value", str(user.role)),
                    # Where from, when the request carried it. Not a precise
                    # location and not meant to be one.
                    "address": address or "",
                },
            ))
    except Exception as e:
        logger.warning(
            "login_history.record_login: could not record the sign-in for "
            "%s: %s: %s", user.email, type(e).__name__, e)


async def for_email(session: AsyncSession, email: str) -> List[dict]:
    """Every recorded sign-in for this address, newest first."""
    user = (await session.execute(
        select(User).where(User.email == (email or "").strip().lower())
    )).scalars().first()
    if user is None:
        return []

    rows = (await session.execute(
        select(AuditLog)
        .where(AuditLog.user_id == user.id, AuditLog.action == LOGIN)
        .order_by(AuditLog.created_at.desc())
        .limit(MAX_ENTRIES)
    )).scalars().all()

    return [
        {
            "at": row.created_at.isoformat(),
            "address": (row.metadata_json or {}).get("address", ""),
            "role": (row.metadata_json or {}).get("role", ""),
        }
        for row in rows
    ]
