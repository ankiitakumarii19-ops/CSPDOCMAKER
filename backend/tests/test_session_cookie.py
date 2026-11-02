# -*- coding: utf-8 -*-
"""The sign-in in a protected cookie (No. 173).

The browser asks for it (X-Session-Cookie: 1) and gets an HttpOnly,
SameSite=Strict cookie with no token in the body; scripts keep Bearer. A
cookie-signed change needs X-Requested-With: CSPDocMaker; logout removes it.
"""

import pytest

from app.config import get_settings
from app.models.enums import AccountStatus, UserRole
from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from app.services import auth_service, google_login, google_sheets_service
from app.workspace_context import all_workspaces
from tests.conftest import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")

EMAIL = "cookie.user@eko.co.in"
BROWSER = {"X-Session-Cookie": "1", "X-Requested-With": "CSPDocMaker"}


@pytest.fixture
async def account(db, monkeypatch):
    db.add(User(email=EMAIL, name="Cookie User", mobile="", role=UserRole.ADMIN,
                account_status=AccountStatus.ACTIVE,
                password_hash=auth_service.hash_password("Password123!")))
    with all_workspaces():
        db.add(WorkspaceMember(workspace_id=DEFAULT_WORKSPACE_ID, email=EMAIL,
                               role=UserRole.ADMIN, active=True))
    await db.commit()
    # Sign in through Google's path: no emailed code to catch.
    monkeypatch.setattr(get_settings(), "google_client_id", "test.apps")
    monkeypatch.setattr(google_login, "_verify_sync", lambda c, i: {
        "email": EMAIL, "email_verified": True, "name": "Cookie User"})
    monkeypatch.setattr(google_sheets_service, "check_authorization",
                        lambda e, r: (False, None))


async def _browser_sign_in(client):
    return await client.post("/api/auth/google", headers=BROWSER,
                             json={"credential": "x" * 30})


async def test_the_browser_gets_a_protected_cookie_and_no_token(
        strict_client, account):
    r = await _browser_sign_in(strict_client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["signed_in"] is True and body["role"] == "admin"
    assert not body.get("access_token") and not body.get("refresh_token")
    cookie = r.headers["set-cookie"].lower()
    assert get_settings().session_cookie_name in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie


async def test_a_script_still_gets_the_token(strict_client, account):
    r = await strict_client.post("/api/auth/google", json={"credential": "x" * 30})
    assert r.json()["access_token"] and "set-cookie" not in r.headers


async def test_the_cookie_signs_in_later_requests(strict_client, account):
    await _browser_sign_in(strict_client)
    r = await strict_client.get("/api/admin/quality/texts", headers=BROWSER)
    assert r.status_code == 200, r.text


async def test_a_change_without_the_apps_header_is_refused(strict_client, account):
    """Another site can make the browser send the cookie, not the header."""
    await _browser_sign_in(strict_client)
    r = await strict_client.put("/api/admin/quality/texts/guardrails",
                                json={"items": []})
    assert r.status_code == 403
    assert "did not come from the app" in r.json()["detail"]


async def test_reading_without_the_header_is_fine(strict_client, account):
    await _browser_sign_in(strict_client)
    r = await strict_client.get("/api/admin/quality/texts")
    assert r.status_code == 200


async def test_logout_removes_the_cookie(strict_client, account):
    await _browser_sign_in(strict_client)
    r = await strict_client.post("/api/auth/logout", headers=BROWSER)
    assert r.status_code == 200
    assert get_settings().session_cookie_name in r.headers["set-cookie"]
    strict_client.cookies.clear()
    r = await strict_client.get("/api/admin/quality/texts", headers=BROWSER)
    assert r.status_code == 401
