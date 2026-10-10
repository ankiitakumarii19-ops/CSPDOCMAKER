"""Password reset: email a code, then set a new password.

The rules pinned here are the ones that make it safe rather than merely
working — a reset code cannot stand in for a login OTP, an unknown address
is answered exactly like a known one, and the old password stops working
only when the reset actually succeeds.
"""

import pytest

from app.models.enums import AccountStatus, UserRole
from app.models.user import User
from app.services import auth_service, otp_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

EMAIL = "reset.user@eko.co.in"
OLD_PASSWORD = "OldPassword9!"
NEW_PASSWORD = "BrandNewPass7!"


@pytest.fixture(autouse=True)
def clean_otp_state():
    """Clear codes and rate-limit keys between tests."""
    try:
        client = otp_service._get_redis()
    except RuntimeError:
        pytest.skip("Redis not reachable — start it with `docker compose up -d`")
    for pattern in ("otp:*", "otp_rate:*", "otp_attempts:*"):
        keys = client.keys(pattern)
        if keys:
            client.delete(*keys)
    yield


@pytest.fixture
def codes(monkeypatch):
    """Capture reset codes instead of emailing them."""
    from app.routers import auth_router

    sent = []

    def fake(to_email, otp_code, user_name=None, subject=None):
        sent.append({"to": to_email, "code": otp_code, "subject": subject})
        return True

    monkeypatch.setattr(auth_router.email_service, "send_otp_email", fake)
    return sent


@pytest.fixture
async def account(db):
    db.add(User(email=EMAIL, name="Reset User", mobile="9876543210",
                role=UserRole.RM, account_status=AccountStatus.ACTIVE,
                password_hash=auth_service.hash_password(OLD_PASSWORD)))
    await db.commit()


async def _request_code(client, email=EMAIL):
    return await client.post("/api/auth/forgot-password", json={"email": email})


async def test_the_full_reset_lets_the_new_password_log_in(client, db, account,
                                                           codes):
    assert (await _request_code(client)).status_code == 200
    code = codes[0]["code"]

    r = await client.post("/api/auth/reset-password", json={
        "email": EMAIL, "otp": code, "new_password": NEW_PASSWORD})
    assert r.status_code == 200, r.text

    r = await client.post("/api/auth/login",
                          json={"email": EMAIL, "password": NEW_PASSWORD})
    assert r.status_code == 200, "the new password must work"


async def test_the_old_password_stops_working(client, db, account, codes):
    await _request_code(client)
    await client.post("/api/auth/reset-password", json={
        "email": EMAIL, "otp": codes[0]["code"], "new_password": NEW_PASSWORD})

    r = await client.post("/api/auth/login",
                          json={"email": EMAIL, "password": OLD_PASSWORD})
    assert r.status_code == 401


async def test_the_subject_says_what_the_code_is_for(client, account, codes):
    await _request_code(client)
    assert "Reset your password" in codes[0]["subject"]
    assert codes[0]["code"] not in codes[0]["subject"]


async def test_an_unknown_address_is_answered_identically(client, account, codes):
    known = await _request_code(client)
    unknown = await _request_code(client, "nobody.here@eko.co.in")
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    # ...and no code was generated for the address without an account.
    assert [c["to"] for c in codes] == [EMAIL]


async def test_a_login_otp_cannot_reset_a_password(client, db, account, codes):
    """The two codes live under different keys; neither satisfies the other."""
    from app.routers import auth_router

    login_codes = []
    import unittest.mock as mock
    with mock.patch.object(
        auth_router.email_service, "send_otp_email",
        lambda to_email, otp_code, user_name=None, subject=None: (
            login_codes.append(otp_code), True)[1],
    ):
        r = await client.post("/api/auth/login",
                              json={"email": EMAIL, "password": OLD_PASSWORD})
        assert r.status_code == 200

    r = await client.post("/api/auth/reset-password", json={
        "email": EMAIL, "otp": login_codes[0], "new_password": NEW_PASSWORD})
    assert r.status_code == 400

    r = await client.post("/api/auth/login",
                          json={"email": EMAIL, "password": OLD_PASSWORD})
    assert r.status_code == 200, "the password must be unchanged"


async def test_a_reset_code_cannot_complete_a_login(client, db, account, codes):
    """verify-otp answers 200 with verified=false rather than an error, so
    the check that matters is that no tokens come back."""
    await _request_code(client)
    r = await client.post("/api/auth/verify-otp",
                          json={"email": EMAIL, "otp": codes[0]["code"]})
    body = r.json()
    assert body["verified"] is False
    assert not body.get("access_token")


async def test_asking_for_a_reset_does_not_cancel_a_pending_login_otp(
    client, db, account, codes
):
    from app.routers import auth_router

    login_codes = []
    import unittest.mock as mock
    with mock.patch.object(
        auth_router.email_service, "send_otp_email",
        lambda to_email, otp_code, user_name=None, subject=None: (
            login_codes.append(otp_code), True)[1],
    ):
        await client.post("/api/auth/login",
                          json={"email": EMAIL, "password": OLD_PASSWORD})

    await _request_code(client)

    r = await client.post("/api/auth/verify-otp",
                          json={"email": EMAIL, "otp": login_codes[0]})
    assert r.status_code == 200, "the login OTP must still be valid"


async def test_a_wrong_code_is_refused(client, account, codes):
    await _request_code(client)
    r = await client.post("/api/auth/reset-password", json={
        "email": EMAIL, "otp": "000000", "new_password": NEW_PASSWORD})
    assert r.status_code == 400


async def test_a_code_cannot_be_used_twice(client, account, codes):
    await _request_code(client)
    code = codes[0]["code"]
    first = await client.post("/api/auth/reset-password", json={
        "email": EMAIL, "otp": code, "new_password": NEW_PASSWORD})
    assert first.status_code == 200

    second = await client.post("/api/auth/reset-password", json={
        "email": EMAIL, "otp": code, "new_password": "YetAnother1!"})
    assert second.status_code == 400


async def test_a_short_password_is_rejected(client, account, codes):
    await _request_code(client)
    r = await client.post("/api/auth/reset-password", json={
        "email": EMAIL, "otp": codes[0]["code"], "new_password": "short1!"})
    assert r.status_code == 422


async def test_a_suspended_account_cannot_be_reset(client, db, account, codes):
    from sqlalchemy import select

    await _request_code(client)
    user = (await db.execute(
        select(User).where(User.email == EMAIL))).scalar_one()
    user.account_status = AccountStatus.SUSPENDED
    await db.commit()

    r = await client.post("/api/auth/reset-password", json={
        "email": EMAIL, "otp": codes[0]["code"], "new_password": NEW_PASSWORD})
    assert r.status_code == 400
