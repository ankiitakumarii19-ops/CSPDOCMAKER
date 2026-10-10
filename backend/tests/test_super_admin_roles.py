# -*- coding: utf-8 -*-
"""Who may configure this system, and who may only watch it.

An Admin who can change a document template can change what every CSP's
official documents say. An Admin who can grant access can grant themselves
anything. Both are the reason the Super Admin role exists, so the separation
is pinned here rather than left to whichever decorator someone remembers.

Super Admins come from configuration rather than the Authorization sheet: a
Super Admin is the person who connects a workspace's sheets in the first
place, so requiring them to already be listed in one is circular.
"""

import pytest

from app.config import get_settings
from app.models.enums import UserRole

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Endpoints that control the platform rather than the work.
#
# Templates and dashboards used to be here. They moved: shaping what a
# document says is operational, and an Admin does it. What stays is who
# may sign in — an Admin who could grant access could grant themselves
# anything. The full split is pinned in test_role_separation.py.
CONFIGURATION = [
    ("GET", "/api/admin/access"),
    ("POST", "/api/admin/access/grant"),
    ("POST", "/api/admin/access/revoke"),
    ("POST", "/api/admin/access/sync"),
]

# Endpoints that only report on what already happened.
MONITORING = [
    "/api/admin/csp-metrics",
    "/api/admin/csp-filters",
    "/api/admin/csp-list",
]


def _token(role: str) -> str:
    from app.services import jwt_service
    return jwt_service.create_access_token({
        "sub": f"{role}@eko.co.in", "email": f"{role}@eko.co.in",
        "role": role, "name": role.title(),
    })


def _auth(role: str) -> dict:
    return {"Authorization": f"Bearer {_token(role)}"}


async def _call(client, method: str, path: str, role: str):
    return await client.request(method, path, headers=_auth(role), json={})


# ---- the role exists and is distinct ------------------------------------

async def test_there_are_three_roles():
    assert {r.value for r in UserRole} == {"rm", "admin", "super_admin"}


# ---- configuration is Super Admin only ----------------------------------

@pytest.mark.parametrize("method,path", CONFIGURATION)
async def test_an_admin_cannot_configure_anything(client, method, path):
    """An Admin watches dashboards. They do not decide what documents say."""
    response = await _call(client, method, path, "admin")
    assert response.status_code == 403, (
        f"an Admin reached {method} {path} — got {response.status_code}")


@pytest.mark.parametrize("method,path", CONFIGURATION)
async def test_an_rm_cannot_configure_anything(client, method, path):
    response = await _call(client, method, path, "rm")
    assert response.status_code == 403


@pytest.mark.parametrize("method,path", CONFIGURATION)
async def test_configuration_needs_a_token_at_all(client, method, path):
    response = await client.request(method, path, json={})
    assert response.status_code in (401, 403)


async def test_a_super_admin_can_reach_configuration(client):
    response = await client.get("/api/admin/access",
                                headers=_auth("super_admin"))
    assert response.status_code == 200


# ---- monitoring is shared ------------------------------------------------

@pytest.mark.parametrize("path", MONITORING)
async def test_both_admin_and_super_admin_see_the_dashboard(client, path):
    """The brief: the existing dashboard stays visible to both."""
    for role in ("admin", "super_admin"):
        response = await client.get(path, headers=_auth(role))
        assert response.status_code == 200, (
            f"{role} could not reach {path}")


@pytest.mark.parametrize("path", MONITORING)
async def test_an_rm_does_not_get_the_admin_dashboard(client, path):
    response = await client.get(path, headers=_auth("rm"))
    assert response.status_code == 403


# ---- where Super Admins come from ---------------------------------------
#
# Changed 11 Oct 2026 (tracker No. 52): Super Admins of Eko SBI Kiosk CSP
# come from the SuperAdmins tab of the Authorization sheet — the same way
# RMs and Admins come from theirs. The SUPER_ADMIN_EMAILS setting listed
# Ganesh as an owner when the sheet said he is an Admin; it is no longer read.

def _sheet_says(monkeypatch, listed: dict):
    """Make the live sheet check answer from `listed` = {email: role}."""
    from app.services import google_sheets_service

    def fake(email, role):
        ok = listed.get(email.lower()) == role
        return ok, ({"Email_id": email, "Contact_no": "9000000000"}
                    if ok else None)
    monkeypatch.setattr(google_sheets_service, "check_authorization", fake)


async def _mirror(db, email, role, active=True):
    """What the 15-minute sync writes for one sheet row."""
    from app.models.authorization_record import AuthorizationRecord
    db.add(AuthorizationRecord(email=email, name=email.split("@")[0],
                               mobile="", role=role, active=active,
                               source="google_sheet"))
    await db.commit()


async def test_the_settings_file_no_longer_makes_anyone_a_super_admin(
        db, monkeypatch):
    from app.services import auth_service

    monkeypatch.setattr(get_settings(), "super_admin_emails",
                        "ganesh.test@eko.co.in")
    _sheet_says(monkeypatch, {"ganesh.test@eko.co.in": "admin"})
    ok, _m, user = await auth_service.signup_user(
        db=db, email="ganesh.test@eko.co.in", name="Ganesh",
        password="a-password", requested_role="admin")
    assert ok and user.role is UserRole.ADMIN


async def test_someone_in_the_superadmins_tab_signs_up_as_super_admin(
        db, monkeypatch):
    from app.services import auth_service

    _sheet_says(monkeypatch, {"owner@eko.co.in": "super_admin"})
    ok, message, user = await auth_service.signup_user(
        db=db, email="owner@eko.co.in", name="Owner",
        password="a-password", requested_role="super_admin")
    assert ok, message
    assert user.role is UserRole.SUPER_ADMIN


async def test_signup_as_super_admin_needs_a_workspace_name(db, monkeypatch):
    """Not in the SuperAdmins tab and no workspace name: nothing to be
    Super Admin of, so it is refused (tracker No. 48)."""
    from app.services import auth_service

    _sheet_says(monkeypatch, {})
    ok, message, user = await auth_service.signup_user(
        db=db, email="someone.else@eko.co.in", name="Someone",
        password="x", requested_role="super_admin")
    assert ok is False
    assert "workspace" in message
    assert user is None


async def test_who_is_a_super_admin_is_read_from_the_mirrored_tab(db):
    from app.services import workspace_service

    assert await workspace_service.sheet_super_admins(db) is None, (
        "never mirrored = unknown, not 'nobody'")
    await _mirror(db, "Owner@Eko.co.in", UserRole.SUPER_ADMIN)
    await _mirror(db, "former@eko.co.in", UserRole.SUPER_ADMIN, active=False)
    await _mirror(db, "admin.only@eko.co.in", UserRole.ADMIN)
    assert await workspace_service.sheet_super_admins(db) == {
        "owner@eko.co.in"}


# ---- the agents' run history is the Owner's alone -----------------------
#
# An Admin runs the agents and reads their findings. The run history is a
# different thing: it records who triggered each pass and every error
# raised, which is an audit of how the workspace has been operated.

AGENT_HISTORY = "/api/admin/agents/monitoring/runs"


async def test_an_admin_cannot_read_the_agents_run_history(client):
    response = await client.get(AGENT_HISTORY, headers=_auth("admin"))
    assert response.status_code == 403, (
        "an Admin could read the run history")


async def test_an_rm_cannot_read_the_agents_run_history(client):
    response = await client.get(AGENT_HISTORY, headers=_auth("rm"))
    assert response.status_code == 403


async def test_the_owner_can_read_the_agents_run_history(client):
    response = await client.get(AGENT_HISTORY, headers=_auth("super_admin"))
    assert response.status_code == 200
    assert "runs" in response.json()


async def test_an_admin_can_still_use_the_agents(client):
    """Restricting the history must not take the screen away from Admins."""
    for path in ("/api/admin/agents", "/api/admin/agents/findings"):
        response = await client.get(path, headers=_auth("admin"))
        assert response.status_code == 200, (
            f"an Admin lost access to {path}")
