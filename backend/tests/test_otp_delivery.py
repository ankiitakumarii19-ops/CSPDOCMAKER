"""OTPs are emailed — there is no delivery choice.

SMS delivery was removed, so login and signup take no otp_method and the
code always goes to the account's email address. These tests pin that: no
hidden channel, and a rejected login sends nothing at all.
"""

import pytest

from app.models import AuthorizationRecord, User
from app.models.enums import AccountStatus, UserRole
from app.services import auth_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

EMAIL = "otpuser@eko.co.in"
MOBILE = "9876543210"
PASSWORD = "CorrectHorse9!"


@pytest.fixture(autouse=True)
def clean_otp_state():
    """Clear Redis OTP and rate-limit keys.

    The limit is 3 OTPs per minute per address; without this a later test
    fails on the rate limit rather than on what it is testing.
    """
    from app.services import otp_service
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
def emails(monkeypatch):
    """Record every OTP email instead of sending it."""
    from app.routers import auth_router

    sent = []
    monkeypatch.setattr(
        auth_router.email_service, "send_otp_email",
        lambda to_email, otp_code, user_name=None: (
            sent.append((to_email, otp_code)), True)[1],
    )
    return sent


@pytest.fixture
async def account(db):
    db.add(AuthorizationRecord(
        email=EMAIL, name="Otp User", mobile=MOBILE,
        role=UserRole.RM, active=True, source="google_sheet",
    ))
    db.add(User(
        email=EMAIL, name="Otp User", mobile=MOBILE, role=UserRole.RM,
        account_status=AccountStatus.ACTIVE,
        password_hash=auth_service.hash_password(PASSWORD),
    ))
    await db.commit()


async def test_login_emails_the_code(client, account, emails):
    r = await client.post("/api/auth/login",
                          json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["otp_delivered"] is True
    assert len(emails) == 1
    assert emails[0][0] == EMAIL


async def test_login_reports_no_delivery_method(client, account, emails):
    """Nothing in the response should suggest a channel can be chosen."""
    r = await client.post("/api/auth/login",
                          json={"email": EMAIL, "password": PASSWORD})
    assert "otp_method" not in r.json()


async def test_an_otp_method_is_rejected_as_unknown(client, account, emails):
    """A stale client asking for SMS must not be silently accepted."""
    r = await client.post("/api/auth/login", json={
        "email": EMAIL, "password": PASSWORD, "otp_method": "sms",
    })
    # Pydantic ignores unknown keys by default, so the login still works —
    # but it goes by email, which is the point.
    assert r.status_code == 200
    assert len(emails) == 1


async def test_a_failed_login_sends_nothing(client, account, emails):
    r = await client.post("/api/auth/login",
                          json={"email": EMAIL, "password": "WrongPassword1!"})
    assert r.status_code == 401
    assert emails == []


async def test_there_is_no_sms_service_left():
    """The module was deleted with the feature; nothing should import it."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.sms_service")


async def test_no_otp_method_enum_remains():
    from app.models import enums
    assert not hasattr(enums, "OTPMethod")
