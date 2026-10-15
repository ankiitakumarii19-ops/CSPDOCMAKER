# -*- coding: utf-8 -*-
"""Admin and Workspace Owner are different, and the difference is enforced.

Three roles, and the line between them is not a label — it is what each one
may CHANGE:

    Workspace Owner  everything an Admin does, PLUS who may sign in
    Admin            monitors everything, and runs the operation:
                     dashboards, document templates and the agents
    RM               works their own assigned CSPs

Shaping the work and controlling access are different things. An Admin
decides what a certificate says; only the Owner decides who may log in.

The dangerous mistakes this guards against, in order:

  * An Admin who can edit a template can change what prints on every
    document that template produces.
  * An Admin who can grant access can grant themselves anything.
  * An Owner who cannot READ records would be responsible for a workspace
    they can see less of than the people they appointed.

Each endpoint is listed explicitly rather than discovered, so adding a new
one without deciding who may reach it makes this file obviously incomplete
rather than silently permissive.
"""

import pytest

from app.models.enums import UserRole
from app.services import csp_access

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER, ADMIN, RM = "super_admin", "admin", "rm"

# Shaping the work. Admins and Owners both.
SHAPING = [
    ("GET", "/api/admin/templates"),
    ("POST", "/api/admin/templates"),
    ("PATCH", "/api/admin/templates/CSP_ID_CARD"),
    ("DELETE", "/api/admin/templates/NOT_REAL"),
    ("PUT", "/api/admin/templates/CSP_ID_CARD/content"),
    ("POST", "/api/admin/templates/CSP_ID_CARD/version"),
    ("GET", "/api/admin/templates/fields"),
    ("POST", "/api/admin/dashboards"),
    ("PATCH", "/api/admin/dashboards/not-real"),
    ("DELETE", "/api/admin/dashboards/not-real"),
    ("GET", "/api/admin/dashboards/metrics"),
]

# Controlling the platform. The Workspace Owner alone.
OWNER_ONLY = [
    ("GET", "/api/admin/access"),
    ("POST", "/api/admin/access/grant"),
    ("POST", "/api/admin/access/revoke"),
    ("POST", "/api/admin/access/sync"),
    # Acting on the agents (decided 12 Oct 2026, No. 88): an approval can
    # message many CSPs, so it is the Owner's; Admins can watch them.
    ("PATCH", "/api/admin/agents/data"),
    ("POST", "/api/admin/agents/setup/run"),
    ("POST", "/api/admin/agents/findings/not-a-uuid/accept"),
    ("POST", "/api/admin/agents/findings/not-a-uuid/reject"),
    # Since 14 Oct 2026 (No. 104) the agents are the Super Admin's alone —
    # Admins no longer even see them.
    ("GET", "/api/admin/agents"),
    ("GET", "/api/admin/agents/findings"),
]

# Looking at what already happened.
MONITORING = [
    "/api/admin/csp-metrics",
    "/api/admin/csp-filters",
    "/api/admin/csp-list",
    "/api/admin/dashboards",
    # Who got which WhatsApp (No. 110).
    "/api/admin/whatsapp-messages",
]

# Reading records. An Owner must see at least what an Admin sees.
READING = [
    "/api/csps/search?q=1A",
    "/api/alerts",
]

# Doing the work. Neither monitor role may.
RM_WORK = [
    ("PATCH", "/api/csps/1A850466"),
    ("POST", "/api/workflows/process"),
    ("POST", "/api/documents/generate/1A850466"),
]


def _auth(role: str) -> dict:
    from app.services import jwt_service

    token = jwt_service.create_access_token({
        "sub": f"{role}@eko.co.in", "email": f"{role}@eko.co.in",
        "role": role, "name": role,
    })
    return {"Authorization": f"Bearer {token}"}


async def _status(client, method: str, path: str, role: str) -> int:
    response = await client.request(method, path, headers=_auth(role), json={})
    return response.status_code


# ---- the roles exist and are distinct -----------------------------------

async def test_there_are_three_distinct_roles():
    assert {r.value for r in UserRole} == {"rm", "admin", "super_admin"}
    assert UserRole.ADMIN is not UserRole.SUPER_ADMIN


# ---- shaping the work: Admins and Owners both ---------------------------

@pytest.mark.parametrize("method,path", SHAPING)
async def test_an_admin_may_shape_the_work(client, method, path):
    """Dashboards and templates are operational, not platform, work."""
    assert await _status(client, method, path, ADMIN) != 403, (
        f"an Admin was refused {method} {path}")


@pytest.mark.parametrize("method,path", SHAPING)
async def test_the_owner_may_shape_the_work(client, method, path):
    assert await _status(client, method, path, OWNER) != 403


@pytest.mark.parametrize("method,path", SHAPING)
async def test_an_rm_may_not(client, method, path):
    assert await _status(client, method, path, RM) == 403


# ---- controlling the platform: the Owner alone --------------------------

@pytest.mark.parametrize("method,path", OWNER_ONLY)
async def test_an_admin_cannot_control_access(client, method, path):
    """An Admin who could grant access could grant themselves anything.

    This is now the ONLY thing an Admin cannot do. Templates, dashboards
    and the agents all moved to them — shaping and running the work is
    operational. Deciding who may log in is not.
    """
    assert await _status(client, method, path, ADMIN) == 403, (
        f"an Admin reached {method} {path}")


@pytest.mark.parametrize("method,path", OWNER_ONLY)
async def test_an_rm_cannot_either(client, method, path):
    assert await _status(client, method, path, RM) == 403


@pytest.mark.parametrize("method,path", OWNER_ONLY)
async def test_the_owner_can(client, method, path):
    assert await _status(client, method, path, OWNER) != 403


# ---- monitoring is shared ------------------------------------------------

@pytest.mark.parametrize("path", MONITORING)
async def test_both_monitor_roles_see_the_dashboards(client, path):
    for role in (ADMIN, OWNER):
        assert await _status(client, "GET", path, role) == 200, (
            f"{role} could not reach {path}")


@pytest.mark.parametrize("path", MONITORING)
async def test_an_rm_does_not_get_the_admin_screens(client, path):
    assert await _status(client, "GET", path, RM) == 403


# ---- an owner must not see LESS than an admin ---------------------------

@pytest.mark.parametrize("path", READING)
async def test_the_owner_can_read_what_an_admin_can_read(client, path):
    """The gap this closes: require_any_role predated the role and locked
    the Workspace Owner out of records their own Admins could see."""
    admin = await _status(client, "GET", path, ADMIN)
    owner = await _status(client, "GET", path, OWNER)
    assert owner == admin, (
        f"{path}: admin got {admin} but the owner got {owner}")
    assert owner != 403


async def test_the_owner_monitors_every_record_like_an_admin():
    """No row filter applies to either monitor role."""
    assert csp_access.is_admin({"role": "super_admin"})
    assert csp_access.is_admin({"role": "admin"})
    assert not csp_access.is_admin({"role": "rm"})
    assert csp_access.accessible_filter({"role": "super_admin"}) is None


# ---- neither monitor role does the RM's job -----------------------------

@pytest.mark.parametrize("method,path", RM_WORK)
async def test_neither_monitor_role_can_do_rm_work(client, method, path):
    """Admin is monitor-only, and configuring is not the same as operating."""
    for role in (ADMIN, OWNER):
        assert await _status(client, method, path, role) == 403, (
            f"{role} reached {method} {path}")


# ---- the distinction is not only on the server --------------------------

async def test_the_admin_screen_admits_both_monitor_roles():
    """A Super Admin bounced off /admin lands on /rm, which bounces back."""
    import pathlib

    page = pathlib.Path("../frontend/app/admin/page.tsx")
    if not page.exists():
        pytest.skip("frontend not present")
    source = page.read_text(encoding="utf-8")
    assert "ADMIN_ROLES" in source
    assert '"super_admin"' in source


async def test_the_two_capabilities_are_named_apart_in_the_ui():
    """An Admin should not be shown a door they cannot open.

    canConfigure gates dashboards and templates; isOwner gates Access.
    Collapsing them into one flag is how an Admin ends up with a button
    that 403s.
    """
    import pathlib

    page = pathlib.Path("../frontend/app/admin/page.tsx")
    if not page.exists():
        pytest.skip("frontend not present")
    source = page.read_text(encoding="utf-8")

    assert 'const isOwner = user?.role === "super_admin"' in source
    assert "const canConfigure = isOwner" in source
    # Templates and the builder are behind the shared flag.
    assert 'canConfigure && adminRoute === "templates"' in source
    assert 'canConfigure && adminRoute === "build"' in source
    # Access is behind the owner's alone.
    assert 'isOwner && adminRoute === "access"' in source
