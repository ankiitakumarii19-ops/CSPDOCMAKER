# -*- coding: utf-8 -*-
"""The Supreme Owner's console, plans and announcements (No. 240, Stage 6).

Brief check 5: organisation administrators cannot reach platform-owner
controls. Also: the console shows counts and health, never a CSP's details;
suspend / reactivate; plans with limits that only bite where set (never on
Eko); announcements reach the right workspaces.
"""

import uuid

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.services import jwt_service, plan_limits, workspace_service, workspace_settings
from app.workspace_context import all_workspaces, workspace

pytestmark = pytest.mark.asyncio(loop_scope="session")

BOSS = "supreme.boss@eko.co.in"
MARK = "ZQPLATFORMMARK"


async def _ws(owner):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        ws = await workspace_service.create_workspace(
            s, f"Plat {uuid.uuid4().hex[:6]}", owner, "Owner")
        await s.commit()
        return ws


async def _drop(*wss):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with all_workspaces():
            for ws in wss:
                await s.execute(text("DELETE FROM workspaces WHERE id = :w").bindparams(w=ws.id))
            await s.execute(text("DELETE FROM plans WHERE key LIKE 'test_%'"))
            await s.execute(text("DELETE FROM platform_announcements"))
            await s.commit()
    workspace_settings.forget()


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


@pytest.fixture
def boss(monkeypatch):
    monkeypatch.setattr(get_settings().server, "supreme_owner_emails", BOSS)
    yield BOSS


async def test_a_workspace_super_admin_is_refused_the_console(strict_client, migrated_db, boss):
    owner, admin = "plat.owner@eko.co.in", "plat.admin@eko.co.in"
    ws = await _ws(owner)
    try:
        await _member(ws, admin, "admin")
        for who, role in ((owner, "super_admin"), (admin, "admin")):
            for method, path in (("GET", "/api/platform/overview"), ("GET", "/api/platform/workspaces"),
                                 ("GET", "/api/platform/plans"),
                                 ("POST", f"/api/platform/workspaces/{ws.id}/suspend")):
                r = await strict_client.request(method, path, headers=_h(ws, who, role))
                assert r.status_code == 403, (role, path, r.status_code)
        me = (await strict_client.get("/api/me/platform", headers=_h(ws, owner))).json()
        assert me == {"supreme_owner": False}
    finally:
        await _drop(ws)


async def test_closed_when_nobody_is_named(strict_client, migrated_db, monkeypatch):
    monkeypatch.setattr(get_settings().server, "supreme_owner_emails", "")
    ws = await _ws(BOSS)
    try:
        r = await strict_client.get("/api/platform/overview", headers=_h(ws, BOSS))
        assert r.status_code == 403
    finally:
        await _drop(ws)


async def test_the_console_counts_and_never_shows_csp_details(strict_client, migrated_db, boss):
    home, other = await _ws(BOSS), await _ws("plat.o2@eko.co.in")
    try:
        from app.database import async_session_factory
        async with async_session_factory() as s:
            with workspace(other.id):
                s.add(CSPRecord(csp_id=f"{MARK}1", csp_code=f"{MARK}1", name=f"{MARK} Person",
                                email=f"{MARK.lower()}@example.com", origin="new",
                                rm_resolution="unresolved"))
                await s.commit()
        h = _h(home, BOSS)
        assert (await strict_client.get("/api/me/platform", headers=h)).json() == {"supreme_owner": True}
        o = await strict_client.get("/api/platform/overview", headers=h)
        assert o.status_code == 200, o.text
        body = o.json()
        assert body["workspaces"] >= 2 and body["active_workspaces"] >= 2
        assert body["health"]["database"] == "ok"
        w = await strict_client.get("/api/platform/workspaces", headers=h)
        rows = {x["id"]: x for x in w.json()["workspaces"]}
        assert rows[str(other.id)]["usage"]["records"] == 1
        eko = next(x for x in rows.values() if x["is_eko"])
        assert eko["subscription"]["plan_key"] == "unlimited"
        assert eko["subscription"]["status"] == "unlimited"
        for r in (o, w):
            assert MARK not in r.text and MARK.lower() not in r.text
    finally:
        await _drop(home, other)


async def test_suspend_locks_the_workspace_out_and_reactivate_lets_it_in(strict_client, migrated_db, boss):
    home, other = await _ws(BOSS), await _ws("plat.o3@eko.co.in")
    try:
        h = _h(home, BOSS)
        member = _h(other, "plat.o3@eko.co.in")
        assert (await strict_client.get("/api/me/access", headers=member)).status_code == 200
        r = await strict_client.post(f"/api/platform/workspaces/{other.id}/suspend", headers=h)
        assert r.status_code == 200 and r.json()["active"] is False
        assert (await strict_client.get("/api/me/access", headers=member)).status_code == 403
        r = await strict_client.post(f"/api/platform/workspaces/{other.id}/reactivate", headers=h)
        assert r.json()["active"] is True
        assert (await strict_client.get("/api/me/access", headers=member)).status_code == 200
        # Never Eko; never the workspace one is signed in to.
        rows = (await strict_client.get("/api/platform/workspaces", headers=h)).json()["workspaces"]
        eko = next(x for x in rows if x["is_eko"])
        assert (await strict_client.post(f"/api/platform/workspaces/{eko['id']}/suspend",
                                         headers=h)).status_code == 409
        assert (await strict_client.post(f"/api/platform/workspaces/{home.id}/suspend",
                                         headers=h)).status_code == 409
    finally:
        await _drop(home, other)


async def test_a_plan_limit_applies_only_where_set_and_never_to_eko(strict_client, migrated_db, boss):
    home, other = await _ws(BOSS), await _ws("plat.o4@eko.co.in")
    try:
        h = _h(home, BOSS)
        r = await strict_client.post("/api/platform/plans", headers=h, json={
            "key": "test_small", "name": "Test small", "max_users": 1,
            "max_documents_month": 5, "price_monthly_paise": 99900})
        assert r.status_code == 201, r.text
        r = await strict_client.put(f"/api/platform/workspaces/{other.id}/subscription", headers=h,
                                    json={"plan_key": "test_small", "status": "trial",
                                          "custom_domain": "docs.example.com", "white_label": True})
        assert r.status_code == 200, r.text
        row = next(x for x in r.json()["workspaces"] if x["id"] == str(other.id))
        assert row["subscription"]["limits"]["max_users"] == 1
        assert row["subscription"]["custom_domain"] == "docs.example.com"
        # The owner is the one active person: adding a second is refused.
        r = await strict_client.post("/api/admin/access/grant", headers=_h(other, "plat.o4@eko.co.in"),
                                     json={"email": "second.person@eko.co.in", "name": "Two", "role": "rm"})
        assert r.status_code == 409 and "allows 1 people" in r.json()["detail"]
        # The documents limit (the same "waiting:" as the daily ceiling).
        with workspace(other.id):
            limits = plan_limits._limits_sync(other.id)
            assert limits["max_documents_month"] == 5 and limits["documents_this_month"] == 0
            plan_limits.check_documents(5)
            with pytest.raises(RuntimeError, match="waiting: .*5 documents a month"):
                plan_limits.check_documents(6)
        # Eko: Unlimited, and cannot be moved off it.
        rows = (await strict_client.get("/api/platform/workspaces", headers=h)).json()["workspaces"]
        eko = next(x for x in rows if x["is_eko"])
        assert plan_limits._limits_sync(eko["id"]) is None
        r = await strict_client.put(f"/api/platform/workspaces/{eko['id']}/subscription", headers=h,
                                    json={"plan_key": "test_small", "status": "active"})
        assert r.status_code == 409
        r = await strict_client.put("/api/platform/plans/unlimited", headers=h,
                                    json={"name": "Unlimited", "max_users": 3})
        assert r.status_code == 409
        # A workspace with no plan has no limit.
        assert plan_limits._limits_sync(home.id) is None
    finally:
        await _drop(home, other)


async def test_bad_subscription_values_are_refused(strict_client, migrated_db, boss):
    home = await _ws(BOSS)
    try:
        h = _h(home, BOSS)
        for body, code in (({"plan_key": "nope"}, 400),
                           ({"plan_key": "unlimited", "status": "free_forever"}, 400),
                           ({"plan_key": "unlimited", "custom_domain": "not a domain"}, 400)):
            r = await strict_client.put(f"/api/platform/workspaces/{home.id}/subscription",
                                        headers=h, json=body)
            assert r.status_code == code, (body, r.text)
    finally:
        await _drop(home)


async def test_announcements_reach_the_right_workspaces(strict_client, migrated_db, boss):
    home, a, b = await _ws(BOSS), await _ws("plat.a@eko.co.in"), await _ws("plat.b@eko.co.in")
    try:
        h = _h(home, BOSS)
        everyone = (await strict_client.post("/api/platform/announcements", headers=h,
                                             json={"message": "Maintenance on Sunday 10 pm"})).json()
        only_a = (await strict_client.post("/api/platform/announcements", headers=h,
                                           json={"message": "Your plan renews soon", "level": "warning",
                                                 "workspace_id": str(a.id)})).json()
        seen_a = [x["message"] for x in (await strict_client.get(
            "/api/me/announcements", headers=_h(a, "plat.a@eko.co.in"))).json()["announcements"]]
        seen_b = [x["message"] for x in (await strict_client.get(
            "/api/me/announcements", headers=_h(b, "plat.b@eko.co.in"))).json()["announcements"]]
        assert set(seen_a) == {everyone["message"], only_a["message"]}
        assert seen_b == [everyone["message"]]
        await strict_client.delete(f"/api/platform/announcements/{everyone['id']}", headers=h)
        seen_b = (await strict_client.get("/api/me/announcements",
                                          headers=_h(b, "plat.b@eko.co.in"))).json()["announcements"]
        assert seen_b == []
        # Only the Supreme Owner announces.
        r = await strict_client.post("/api/platform/announcements", headers=_h(a, "plat.a@eko.co.in"),
                                     json={"message": "hello everyone"})
        assert r.status_code == 403
    finally:
        await _drop(home, a, b)
