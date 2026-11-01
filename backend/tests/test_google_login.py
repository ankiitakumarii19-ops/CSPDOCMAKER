# -*- coding: utf-8 -*-
"""Log in with Google (No. 171).

Google's check of the address replaces the emailed code; who may enter does
not change. The same email is the same account, in any capitals.
"""

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models.enums import AccountStatus, UserRole
from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from app.services import auth_service, google_login, google_sheets_service, jwt_service
from app.workspace_context import all_workspaces
from tests.conftest import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")

TOKEN = "a-google-id-token-long-enough"


@pytest.fixture
def google(monkeypatch):
    """Google's answer, without Google: set claims["email"] per test."""
    monkeypatch.setattr(get_settings(), "google_client_id", "test-client.apps")
    claims = {"email_verified": True, "name": "From Google"}
    seen = {}

    def fake(credential, client_id):
        seen["client_id"] = client_id
        if credential != TOKEN:
            raise ValueError("Wrong number of segments")
        return dict(claims)

    monkeypatch.setattr(google_login, "_verify_sync", fake)
    # Nobody is on the sheet unless a test says so.
    monkeypatch.setattr(google_sheets_service, "check_authorization",
                        lambda email, role: (False, None))
    return claims, seen


async def _account(db, email, status=AccountStatus.ACTIVE):
    db.add(User(email=email, name="Has Password", mobile="", role=UserRole.RM,
                account_status=status,
                password_hash=auth_service.hash_password("Password123!")))
    with all_workspaces():
        db.add(WorkspaceMember(workspace_id=DEFAULT_WORKSPACE_ID,
                               email=email.lower(), role=UserRole.RM,
                               active=True))
    await db.commit()


async def _sign_in(client):
    return await client.post("/api/auth/google", json={"credential": TOKEN})


async def test_the_button_shows_only_when_a_client_id_is_set(
        strict_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "")
    assert (await strict_client.get("/api/auth/config")).json()[
        "google_client_id"] == ""
    monkeypatch.setattr(get_settings(), "google_client_id", "abc.apps")
    assert (await strict_client.get("/api/auth/config")).json()[
        "google_client_id"] == "abc.apps"


async def test_off_without_a_client_id(strict_client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "")
    assert (await _sign_in(strict_client)).status_code == 404


async def test_an_existing_account_signs_in_without_a_code(
        strict_client, db, google):
    claims, seen = google
    await _account(db, "ankita@eko.co.in")
    claims["email"] = "ankita@eko.co.in"

    response = await _sign_in(strict_client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"] and body["role"] == "rm"
    assert body["email"] == "ankita@eko.co.in"
    assert jwt_service.verify_access_token(body["access_token"])["sub"] == \
        "ankita@eko.co.in"
    assert seen["client_id"] == "test-client.apps"


async def test_same_email_in_other_capitals_is_the_same_account(
        strict_client, db, google):
    claims, _ = google
    await _account(db, "Ankita.Kumari@eko.co.in")
    claims["email"] = "ankita.kumari@eko.co.in"

    assert (await _sign_in(strict_client)).status_code == 200
    with all_workspaces():
        count = (await db.execute(select(func.count()).select_from(User).where(
            func.lower(User.email) == "ankita.kumari@eko.co.in"))).scalar()
    assert count == 1, "no second account"


async def test_a_pending_account_is_activated(strict_client, db, google):
    claims, _ = google
    await _account(db, "pending@eko.co.in", status=AccountStatus.PENDING)
    claims["email"] = "pending@eko.co.in"
    assert (await _sign_in(strict_client)).status_code == 200
    db.expire_all()
    user = await auth_service.get_user_by_email(db, "pending@eko.co.in")
    assert user.account_status == AccountStatus.ACTIVE


async def test_a_suspended_account_is_refused(strict_client, db, google):
    claims, _ = google
    await _account(db, "stopped@eko.co.in", status=AccountStatus.SUSPENDED)
    claims["email"] = "stopped@eko.co.in"
    response = await _sign_in(strict_client)
    assert response.status_code == 403
    assert "suspended" in response.json()["detail"]


async def test_someone_not_on_the_list_gets_no_account(
        strict_client, db, google):
    claims, _ = google
    claims["email"] = "stranger@gmail.com"
    response = await _sign_in(strict_client)
    assert response.status_code == 403
    assert "has not been added" in response.json()["detail"]
    assert await auth_service.get_user_by_email(db, "stranger@gmail.com") is None


async def test_someone_on_the_rm_tab_gets_an_account_once(
        strict_client, db, google, monkeypatch):
    claims, _ = google
    claims["email"] = "new.rm@eko.co.in"
    monkeypatch.setattr(google_sheets_service, "check_authorization",
                        lambda email, role: (role == "rm", {"Email": email}))

    first = await _sign_in(strict_client)
    assert first.status_code == 200, first.text
    assert first.json()["role"] == "rm"
    second = await _sign_in(strict_client)
    assert second.status_code == 200
    with all_workspaces():
        users = (await db.execute(select(User).where(
            User.email == "new.rm@eko.co.in"))).scalars().all()
    assert len(users) == 1
    assert users[0].name == "From Google"
    assert users[0].account_status == AccountStatus.ACTIVE


async def test_an_unverified_google_address_is_refused(
        strict_client, db, google):
    claims, _ = google
    await _account(db, "unverified@eko.co.in")
    claims.update(email="unverified@eko.co.in", email_verified=False)
    assert (await _sign_in(strict_client)).status_code == 401


async def test_a_forged_token_is_refused(strict_client, db, google):
    claims, _ = google
    await _account(db, "victim@eko.co.in")
    claims["email"] = "victim@eko.co.in"
    response = await strict_client.post(
        "/api/auth/google", json={"credential": "x" * 40})
    assert response.status_code == 401
    assert not response.json().get("access_token")


async def test_the_sign_in_is_recorded_as_google(strict_client, db, google):
    from app.models.audit_log import AuditLog

    claims, _ = google
    await _account(db, "recorded@eko.co.in")
    claims["email"] = "recorded@eko.co.in"
    assert (await _sign_in(strict_client)).status_code == 200
    with all_workspaces():
        row = (await db.execute(select(AuditLog).where(
            AuditLog.action == "login"))).scalars().first()
    assert row.metadata_json["method"] == "google"
