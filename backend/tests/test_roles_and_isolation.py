# -*- coding: utf-8 -*-
"""Starter roles and isolation by direct request (No. 240, Stage 4).

Brief checks: 4 users cannot reach another organisation's records through
direct API requests, manipulated ids or a manipulated sign-in; flexible roles
(Manager, Employee, Reviewer, Viewer) on top of the existing RM / Admin.
The list-route isolation check is tests/test_safety.py (No. 216).
"""

import uuid

import pytest
from sqlalchemy import text

from app.models.csp_record import CSPRecord
from app.services import feature_access, jwt_service, workspace_service, workspace_settings
from app.workspace_context import all_workspaces, workspace

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _ws(owner):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        ws = await workspace_service.create_workspace(
            s, f"Roles {uuid.uuid4().hex[:6]}", owner, "Owner")
        await s.commit()
        return ws


async def _drop(*wss):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with all_workspaces():
            for ws in wss:
                await s.execute(text("DELETE FROM workspaces WHERE id = :w").bindparams(w=ws.id))
            await s.commit()
    workspace_settings.forget()
    feature_access.forget()


def _h(ws, email, role="super_admin"):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": email, "email": email, "role": role, "name": "X", "ws": str(ws.id)})}


async def _member(ws, email, role):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        await s.execute(text(
            "INSERT INTO workspace_members (id, workspace_id, email, name, role, "
            "active, created_at, updated_at) VALUES (gen_random_uuid(), :w, :e, "
            "'X', CAST(:r AS user_role), true, now(), now())").bindparams(
                w=ws.id, e=email, r=role.upper()))
        await s.commit()


async def test_starter_roles_are_added_once_and_are_ordinary_roles(strict_client, migrated_db):
    owner = "roles.o@eko.co.in"
    ws = await _ws(owner)
    try:
        r = await strict_client.post("/api/admin/feature-access/starter-roles", headers=_h(ws, owner))
        assert r.status_code == 201, r.text
        assert r.json()["added"] == ["Manager", "Employee", "Reviewer", "Viewer"]
        names = {x["name"] for x in r.json()["roles"]}
        assert {"Manager", "Employee", "Reviewer", "Viewer", "RM", "Admin"} <= names
        again = await strict_client.post("/api/admin/feature-access/starter-roles", headers=_h(ws, owner))
        assert again.json()["added"] == []
    finally:
        await _drop(ws)


async def test_only_the_super_admin_adds_starter_roles(strict_client, migrated_db):
    owner, admin = "roles.o2@eko.co.in", "roles.a2@eko.co.in"
    ws = await _ws(owner)
    try:
        await _member(ws, admin, "admin")
        r = await strict_client.post("/api/admin/feature-access/starter-roles",
                                     headers=_h(ws, admin, "admin"))
        assert r.status_code == 403
    finally:
        await _drop(ws)


async def test_a_viewer_looks_but_cannot_act(strict_client, migrated_db):
    owner, person = "roles.o3@eko.co.in", "roles.v3@eko.co.in"
    ws = await _ws(owner)
    try:
        await _member(ws, person, "rm")
        r = await strict_client.post("/api/admin/feature-access/starter-roles", headers=_h(ws, owner))
        viewer = next(x["key"] for x in r.json()["roles"] if x["name"] == "Viewer")
        r = await strict_client.put(f"/api/admin/feature-access/members/{person}/role",
                                    json={"role": viewer}, headers=_h(ws, owner))
        assert r.status_code == 200, r.text
        feature_access.forget()
        me = (await strict_client.get("/api/me/access", headers=_h(ws, person, "rm"))).json()
        assert me["role_name"] == "Viewer"
        assert "csp_search" in me["features"] and "dashboard" in me["features"]
        for gone in ("documents", "csp_message", "csp_edit", "sheets"):
            assert gone not in me["features"], gone
        assert me["record_scope"] == "all"
        # The server refuses, not just the menu.
        r = await strict_client.post("/api/workflows/process", headers=_h(ws, person, "rm"),
                                     json={"csp_id": "X", "document_types": ["CSP_ID_CARD"]})
        assert r.status_code == 403, r.text
        assert (await strict_client.get("/api/csps/search?q=ab", headers=_h(ws, person, "rm"))).status_code == 200
    finally:
        await _drop(ws)


async def test_another_organisations_record_by_its_id_is_not_found(strict_client, migrated_db):
    a_owner, b_owner = "iso.a@eko.co.in", "iso.b@eko.co.in"
    a, b = await _ws(a_owner), await _ws(b_owner)
    try:
        from app.database import async_session_factory
        async with async_session_factory() as s:
            with workspace(a.id):
                rec = CSPRecord(csp_id="ISOREC1", csp_code="ISOREC1", name="Iso Person",
                                origin="new", rm_resolution="unresolved")
                s.add(rec)
                await s.commit()
        assert (await strict_client.get("/api/admin/database/ISOREC1",
                                        headers=_h(a, a_owner))).status_code == 200
        for path in ("/api/admin/database/ISOREC1", "/api/admin/database/ISOREC1/edit",
                     "/api/csps/ISOREC1"):
            r = await strict_client.get(path, headers=_h(b, b_owner))
            assert r.status_code in (403, 404), (path, r.status_code)
            assert "Iso Person" not in r.text
    finally:
        await _drop(a, b)


async def test_a_forged_organisation_in_the_sign_in_is_refused(strict_client, migrated_db):
    a_owner, b_owner = "forge.a@eko.co.in", "forge.b@eko.co.in"
    a, b = await _ws(a_owner), await _ws(b_owner)
    try:
        # A's owner presents a token naming B, where they are not a member.
        r = await strict_client.get("/api/admin/database", headers=_h(b, a_owner))
        assert r.status_code == 403
        # Claiming a higher role than held is refused too.
        await _member(a, "forge.rm@eko.co.in", "rm")
        r = await strict_client.get("/api/admin/settings",
                                    headers=_h(a, "forge.rm@eko.co.in", "super_admin"))
        assert r.status_code == 401
    finally:
        await _drop(a, b)
