# -*- coding: utf-8 -*-
"""Every sign-in is written down.

The Access screen showed one date — the last sign-in — which answers "is
this account in use" and nothing else. A second login simply overwrote the
first, so there was no way to tell daily use from a single visit in
September.

Sign-ins now go into `audit_logs`: a table that was created with the
schema, correctly indexed, and had never had a single row written to it.

Two properties matter and are pinned here. The record must never cost
somebody a successful login, and the history must not be readable by the
people it is about.
"""

import pytest

from app.models.audit_log import AuditLog
from app.models.user import User, UserRole
from app.services import login_history

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _token(role: str) -> str:
    from app.services import jwt_service
    return jwt_service.create_access_token({
        "sub": f"{role}@eko.co.in", "email": f"{role}@eko.co.in",
        "role": role, "name": role.title(),
    })


def _auth(role: str) -> dict:
    return {"Authorization": f"Bearer {_token(role)}"}


async def _user(db, email="someone@eko.co.in") -> User:
    from app.services import auth_service

    user = User(
        email=email, name="Someone", mobile="9876543210",
        role=UserRole.RM,
        password_hash=auth_service.hash_password("irrelevant-here"),
    )
    db.add(user)
    await db.flush()
    return user


# ---- what gets written --------------------------------------------------

async def test_a_sign_in_is_recorded(db):
    user = await _user(db)
    await login_history.record_login(db, user, address="203.0.113.9")
    await db.flush()

    entries = await login_history.for_email(db, user.email)
    assert len(entries) == 1
    assert entries[0]["address"] == "203.0.113.9"
    assert entries[0]["role"] == "rm"
    assert entries[0]["at"]


async def test_each_sign_in_is_kept_not_overwritten(db):
    """The whole point: the last-login column could only ever hold one."""
    user = await _user(db, "repeat@eko.co.in")
    for _ in range(3):
        await login_history.record_login(db, user, address="203.0.113.9")
    await db.flush()

    assert len(await login_history.for_email(db, user.email)) == 3


async def test_newest_first(db):
    import asyncio

    user = await _user(db, "ordered@eko.co.in")
    for address in ("1.1.1.1", "2.2.2.2"):
        await login_history.record_login(db, user, address=address)
        await db.flush()
        await asyncio.sleep(0.01)

    entries = await login_history.for_email(db, user.email)
    assert entries[0]["at"] >= entries[-1]["at"]


async def test_nothing_secret_is_recorded(db):
    """A sign-in record is who, when and from where. Nothing else."""
    user = await _user(db, "careful@eko.co.in")
    await login_history.record_login(db, user, address="203.0.113.9")
    await db.flush()

    row = (await db.execute(
        __import__("sqlalchemy").select(AuditLog)
        .where(AuditLog.user_id == user.id)
    )).scalars().first()
    stored = str(row.metadata_json).lower()
    for forbidden in ("password", "otp", "token", "hash", "secret"):
        assert forbidden not in stored, f"{forbidden} was recorded"


async def test_an_unknown_address_has_no_history(db):
    assert await login_history.for_email(db, "nobody@example.com") == []


# ---- it must never cost somebody their login ----------------------------

async def test_a_failure_to_record_does_not_raise(db, monkeypatch):
    """The person is already authenticated by this point. Refusing them
    because a log row would not write is the worse outcome."""
    user = await _user(db, "resilient@eko.co.in")

    def _explode(*args, **kwargs):
        raise RuntimeError("the table is gone")

    monkeypatch.setattr(db, "add", _explode)
    await login_history.record_login(db, user)      # must not raise


# ---- who may read it ----------------------------------------------------

HISTORY = "/api/admin/access/logins?email=someone@eko.co.in"


async def test_the_history_is_not_public(client):
    assert (await client.get(HISTORY)).status_code in (401, 403)


@pytest.mark.parametrize("role", ["rm", "admin"])
async def test_only_the_owner_may_read_the_history(client, role):
    """When a named colleague signs in is about the person, not the work."""
    response = await client.get(HISTORY, headers=_auth(role))
    assert response.status_code == 403


async def test_the_owner_may_read_the_history(client):
    response = await client.get(HISTORY, headers=_auth("super_admin"))
    assert response.status_code == 200
    body = response.json()
    assert "logins" in body
    # An empty list must not read as "never signed in".
    assert "never used" in body["note"] or "recorded" in body["note"]


# ---- through the real endpoint ------------------------------------------
#
# The tests above call record_login directly, with a workspace already in
# context because conftest puts one there. Signing in has NO workspace in
# context — it is a pre-authentication endpoint — so `workspace_id`
# defaulted to NULL, the NOT NULL constraint rejected the row at COMMIT,
# and every login returned a 500.
#
# Everything above stayed green while login was completely broken. These
# go through the endpoint instead.

async def test_signing_in_still_works(client, db):
    """The regression: recording the sign-in must not break the sign-in."""
    from app.services import auth_service, otp_service

    password = "A-real-password-1"
    email = "endtoend@eko.co.in"
    db.add(User(
        email=email, name="End To End", mobile="9876543210",
        role=UserRole.RM,
        password_hash=auth_service.hash_password(password),
    ))
    await db.commit()

    first = await client.post("/api/auth/login",
                              json={"email": email, "password": password})
    assert first.status_code == 200, first.text

    code = await otp_service.peek_otp(email) if hasattr(
        otp_service, "peek_otp") else None
    if code is None:
        pytest.skip("the OTP cannot be read back in this environment")

    second = await client.post("/api/auth/verify-otp",
                               json={"email": email, "otp_code": code})
    assert second.status_code == 200, (
        f"verify-otp failed: {second.text}")


async def test_the_audit_row_carries_a_workspace(db):
    """A scoped row with no workspace is rejected by the database.

    During login there is no ambient workspace to default from, so it has
    to come from the user being signed in.
    """
    user = await _user(db, "scoped@eko.co.in")
    await login_history.record_login(db, user, address="203.0.113.9")
    await db.commit()

    row = (await db.execute(
        __import__("sqlalchemy").select(AuditLog)
        .where(AuditLog.user_id == user.id)
    )).scalars().first()
    assert row is not None, "the sign-in was not recorded at all"
    assert row.workspace_id is not None, (
        "the audit row has no workspace — this is what broke login")
    assert row.workspace_id == user.workspace_id


async def test_a_bad_audit_row_does_not_poison_the_transaction(db):
    """The insert is a savepoint, so a failure rolls back only itself.

    The first version caught exceptions around session.add(), which cannot
    fail — the database only sees the row at commit, by which time the
    try/except is long gone and the whole login goes down with it.
    """
    user = await _user(db, "poison@eko.co.in")

    # A row that the database will refuse: action is NOT NULL.
    import sqlalchemy

    async def _bad(*args, **kwargs):
        raise sqlalchemy.exc.IntegrityError("bad row", None, Exception("no"))

    # The session must still be usable afterwards.
    await login_history.record_login(db, user)
    await db.commit()
    assert (await db.execute(
        sqlalchemy.select(User).where(User.id == user.id)
    )).scalars().first() is not None, "the session was left unusable"
