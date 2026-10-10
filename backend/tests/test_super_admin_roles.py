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

async def test_a_configured_email_is_a_super_admin(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "super_admin_emails",
                        "owner@eko.co.in, second@ekosupport.in")
    assert settings.is_super_admin("owner@eko.co.in")
    assert settings.is_super_admin("second@ekosupport.in")


async def test_matching_an_owner_ignores_case_and_spacing(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "super_admin_emails", "  Owner@Eko.co.in ")
    assert settings.is_super_admin("owner@eko.co.in")
    assert settings.is_super_admin("  OWNER@EKO.CO.IN  ")


async def test_nobody_else_is_a_super_admin(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "super_admin_emails", "owner@eko.co.in")
    assert not settings.is_super_admin("admin@eko.co.in")
    assert not settings.is_super_admin("")


async def test_an_empty_list_makes_nobody_a_super_admin(monkeypatch):
    """A blank setting must not accidentally grant the role to everyone."""
    settings = get_settings()
    monkeypatch.setattr(settings, "super_admin_emails", "")
    assert settings.super_admins == ()
    assert not settings.is_super_admin("anyone@eko.co.in")


async def test_signup_refuses_to_hand_out_the_role(db, monkeypatch):
    """Nobody talks their way into Super Admin through the signup form."""
    from app.services import auth_service

    settings = get_settings()
    monkeypatch.setattr(settings, "super_admin_emails", "owner@eko.co.in")

    ok, message, user = await auth_service.signup_user(
        db=db, email="someone.else@eko.co.in", name="Someone",
        password="x", requested_role="super_admin",
    )
    assert ok is False
    assert "not configured as a Super Admin" in message
    assert user is None


async def test_a_configured_owner_signing_up_gets_the_role(db, monkeypatch):
    """And the configured one does get it, without being in any sheet."""
    from app.services import auth_service

    settings = get_settings()
    monkeypatch.setattr(settings, "super_admin_emails", "owner@eko.co.in")

    ok, _message, user = await auth_service.signup_user(
        db=db, email="owner@eko.co.in", name="Owner",
        password="a-password", requested_role="rm",
    )
    assert ok is True
    assert user is not None
    assert user.role is UserRole.SUPER_ADMIN, (
        "a configured owner asked for 'rm' and should still be an owner")


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
