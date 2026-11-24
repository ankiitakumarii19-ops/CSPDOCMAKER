"""Feature access and own roles (No. 206, Stage 2).

The first test proves that, with nothing changed, every route allows exactly
who it allowed before. The rest run in a fresh workspace (made the way
sign-up makes one), so Eko's access is never touched.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.models.enums import UserRole
from app.models.workspace_member import WorkspaceMember
from app.services import (assistant_tools, csp_access, feature_access,
                          feature_catalog, jwt_service, workspace_service,
                          workspace_settings)
from app.workspace_context import all_workspaces, workspace

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER = "fa.owner@eko.co.in"
ADMIN = "fa.admin@eko.co.in"
ADMIN2 = "fa.admin2@eko.co.in"
RM1 = "fa.rm1@eko.co.in"
RM2 = "fa.rm2@eko.co.in"


# ---- today's access, route by route -----------------------------------------------

def _roles_of(dep):
    found = []
    call = dep.call
    name = getattr(call, "__qualname__", "")
    if name == "require_any_role":
        found.append(("rm", "admin", "super_admin"))
    if getattr(call, "__closure__", None) and name.endswith("_check"):
        for c in call.__closure__:
            v = c.cell_contents
            if isinstance(v, tuple) and all(isinstance(x, str) for x in v):
                found.append(tuple(x.lower() for x in v))
    for d in dep.dependencies:
        found += _roles_of(d)
    return found


def test_every_route_belongs_to_a_feature_with_todays_access():
    from fastapi.routing import APIRoute
    from app.main import app
    problems, used = [], set()
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        guards = _roles_of(r.dependant)
        for m in r.methods:
            f = feature_catalog.feature_for(m, r.path)
            if not guards:
                if f is not None:
                    problems.append(f"unguarded route in a feature: {m} {r.path}")
                continue
            allowed = set(guards[0])
            for g in guards[1:]:
                allowed &= set(g)
            if f is None:
                if not r.path.startswith(feature_catalog.BASICS):
                    problems.append(f"no feature: {m} {r.path}")
                continue
            used.add(f.key)
            want = set(f.default) | ({"super_admin"} if f.owner else set())
            if want != allowed:
                problems.append(f"{m} {r.path}: feature {f.key} says "
                                f"{sorted(want)}, route {sorted(allowed)}")
    assert not problems, "\n".join(problems)
    assert used == set(feature_catalog.BY_KEY)


# ---- a fresh workspace -----------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_redis_client(monkeypatch):
    monkeypatch.setattr(assistant_tools, "_redis", None)


@pytest.fixture
async def ws(migrated_db):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        created = await workspace_service.create_workspace(
            s, f"Access Test {uuid.uuid4().hex[:6]}", OWNER, "Access Owner")
        with all_workspaces():
            for email, role in ((ADMIN, UserRole.ADMIN), (ADMIN2, UserRole.ADMIN),
                                (RM1, UserRole.RM), (RM2, UserRole.RM)):
                s.add(WorkspaceMember(workspace_id=created.id, email=email,
                                      role=role, active=True))
        await s.commit()
        yield created
        with all_workspaces():
            await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                            .bindparams(w=created.id))
            await s.commit()
    feature_access.forget()
    workspace_settings.forget()


def _h(ws, email=OWNER, role="super_admin"):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": email, "email": email, "role": role,
        "name": email.split("@")[0], "ws": str(ws.id)})}


def _rm(ws, email=RM1):
    return _h(ws, email, "rm")


def _admin(ws, email=ADMIN):
    return _h(ws, email, "admin")


async def _put(client, ws, path, allowed):
    r = await client.put(f"/api/admin/feature-access/{path}",
                         json={"allowed": allowed}, headers=_h(ws))
    return r


async def test_nothing_changed_is_todays_access(strict_client, ws):
    for headers, role in ((_rm(ws), "rm"), (_admin(ws), "admin")):
        body = (await strict_client.get("/api/me/access",
                                        headers=headers)).json()
        assert set(body["features"]) == {
            f.key for f in feature_catalog.FEATURES if role in f.default}
        assert body["record_scope"] == ("own" if role == "rm" else "all")
    owner = (await strict_client.get("/api/me/access", headers=_h(ws))).json()
    assert set(owner["features"]) == {f.key for f in feature_catalog.FEATURES
                                      if f.owner}
    view = (await strict_client.get("/api/admin/feature-access",
                                    headers=_h(ws))).json()
    assert [r["key"] for r in view["roles"]] == ["rm", "admin"]


async def test_a_feature_taken_away_is_refused_by_the_server(strict_client, ws):
    assert (await strict_client.get("/api/admin/whatsapp-messages",
                                    headers=_admin(ws))).status_code == 200
    r = await _put(strict_client, ws, "roles/admin/whatsapp", False)
    assert r.status_code == 200, r.text
    r = await strict_client.get("/api/admin/whatsapp-messages",
                                headers=_admin(ws))
    assert r.status_code == 403
    assert "has not given you “WhatsApp messages”" in r.json()["detail"]
    # the Super Admin keeps it
    assert (await strict_client.get("/api/admin/whatsapp-messages",
                                    headers=_h(ws))).status_code == 200


async def test_a_feature_given_to_rms_lets_them_in(strict_client, ws):
    assert (await strict_client.get("/api/admin/whatsapp-messages",
                                    headers=_rm(ws))).status_code == 403
    r = await _put(strict_client, ws, "roles/rm/whatsapp", True)
    assert r.status_code == 200, r.text
    assert (await strict_client.get("/api/admin/whatsapp-messages",
                                    headers=_rm(ws))).status_code == 200
    me = (await strict_client.get("/api/me/access", headers=_rm(ws))).json()
    assert "whatsapp" in me["features"] and me["admin_area"] is True
    # back to today's access
    await _put(strict_client, ws, "roles/rm/whatsapp", None)
    assert (await strict_client.get("/api/admin/whatsapp-messages",
                                    headers=_rm(ws))).status_code == 403


async def test_one_person_differs_from_their_role(strict_client, ws):
    await _put(strict_client, ws, "roles/admin/emails", False)
    r = await _put(strict_client, ws, f"people/{ADMIN2}/emails", True)
    assert r.status_code == 200, r.text
    assert (await strict_client.get("/api/admin/email-messages",
                                    headers=_admin(ws))).status_code == 403
    assert (await strict_client.get("/api/admin/email-messages",
                                    headers=_admin(ws, ADMIN2))).status_code == 200
    await _put(strict_client, ws, f"people/{RM1}/csp_message", False)
    r = await strict_client.post("/api/csps/NOPE/message", json={},
                                 headers=_rm(ws))
    assert r.status_code == 403


async def test_what_cannot_be_given_or_changed(strict_client, ws):
    r = await _put(strict_client, ws, "roles/admin/documents", True)
    assert r.status_code == 400 and "cannot be given to Admins" in r.json()["detail"]
    r = await _put(strict_client, ws, "roles/admin/access", False)
    assert r.status_code == 400 and "stays with the Super Admin" in r.json()["detail"]
    r = await _put(strict_client, ws, f"people/{OWNER}/dashboard", False)
    assert r.status_code == 400 and "always keeps" in r.json()["detail"]
    r = await strict_client.get("/api/admin/feature-access", headers=_admin(ws))
    assert r.status_code == 403


async def test_an_own_role_built_on_rm(strict_client, ws):
    r = await strict_client.post("/api/admin/feature-access/roles",
                                 json={"name": "Field officer",
                                       "copy_from": "rm"}, headers=_h(ws))
    assert r.status_code == 201, r.text
    key = r.json()["role"]["key"]
    assert key == "field-officer"
    await _put(strict_client, ws, f"roles/{key}/dashboard", True)
    r = await strict_client.put(f"/api/admin/feature-access/members/{RM1}/role",
                                json={"role": key}, headers=_h(ws))
    assert r.status_code == 200, r.text
    assert (await strict_client.get("/api/admin/dashboard",
                                    headers=_rm(ws, RM1))).status_code == 200
    assert (await strict_client.get("/api/admin/dashboard",
                                    headers=_rm(ws, RM2))).status_code == 403
    me = (await strict_client.get("/api/me/access", headers=_rm(ws))).json()
    assert me["role_name"] == "Field officer"
    # an Admin cannot be given a role built on RM
    r = await strict_client.put(f"/api/admin/feature-access/members/{ADMIN}/role",
                                json={"role": key}, headers=_h(ws))
    assert r.status_code == 400 and "built on RM" in r.json()["detail"]
    # a role in use cannot be removed
    r = await strict_client.delete(f"/api/admin/feature-access/roles/{key}",
                                   headers=_h(ws))
    assert r.status_code == 400 and "give them another role" in r.json()["detail"]
    await strict_client.put(f"/api/admin/feature-access/members/{RM1}/role",
                            json={"role": None}, headers=_h(ws))
    r = await strict_client.delete(f"/api/admin/feature-access/roles/{key}",
                                   headers=_h(ws))
    assert r.status_code == 200, r.text
    assert (await strict_client.get("/api/admin/dashboard",
                                    headers=_rm(ws, RM1))).status_code == 403


async def test_which_csps_a_role_may_act_on(strict_client, ws):
    other = SimpleNamespace(rm_email="someone.else@eko.co.in",
                            rm_resolution="matched")
    user = {"role": "rm", "sub": RM1}
    with workspace(ws.id):
        assert csp_access.can_access(other, user) is False
        assert csp_access.accessible_filter(user) is not None
    r = await strict_client.patch("/api/admin/feature-access/roles/rm",
                                  json={"record_scope": "all"}, headers=_h(ws))
    assert r.status_code == 200, r.text
    with workspace(ws.id):
        assert csp_access.can_access(other, user) is True
        assert csp_access.accessible_filter(user) is None
    r = await strict_client.patch("/api/admin/feature-access/roles/admin",
                                  json={"record_scope": "own"}, headers=_h(ws))
    assert r.status_code == 400


async def test_every_change_is_in_the_history(strict_client, ws):
    await _put(strict_client, ws, "roles/admin/knowledge", False)
    await _put(strict_client, ws, "roles/admin/knowledge", None)
    changes = (await strict_client.get("/api/admin/feature-access/history",
                                       headers=_h(ws))).json()["changes"]
    assert [(c["before"], c["after"]) for c in changes[:2]] == [
        ("taken away", "as before (today's access)"),
        ("as before (today's access)", "taken away")]
    assert changes[0]["what"].startswith("Knowledge Base")
    # the Settings history keeps to settings
    settings_changes = (await strict_client.get(
        "/api/admin/settings/history", headers=_h(ws))).json()["changes"]
    assert not any(c["key"].startswith("access:") for c in settings_changes)


# ---- by chat (ZU-02) ---------------------------------------------------------------

async def _chat(client, headers, question):
    r = await client.post("/api/assistant/chat", headers=headers,
                          json={"messages": [{"role": "user",
                                              "content": question}]})
    assert r.status_code == 200, r.text
    return r.json()


async def test_the_chat_gives_a_feature_after_do_it(strict_client, ws):
    body = await _chat(strict_client, _h(ws), "give RMs the dashboard")
    [card] = body["cards"]
    assert card["kind"] == "change_feature_access"
    assert "shows every CSP" in " ".join(card["extra"])
    assert (await strict_client.get("/api/admin/dashboard",
                                    headers=_rm(ws))).status_code == 403
    r = await strict_client.post(f"/api/assistant/actions/{card['id']}/run",
                                 headers=_h(ws))
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert (await strict_client.get("/api/admin/dashboard",
                                    headers=_rm(ws))).status_code == 200
    change = (await strict_client.get("/api/admin/feature-access/history",
                                      headers=_h(ws))).json()["changes"][0]
    assert change["via"] == "chat"


async def test_the_chat_refuses_what_cannot_be_done(strict_client, ws):
    body = await _chat(strict_client, _h(ws), "give admins make documents")
    assert not body["cards"] and "cannot be given to Admins" in body["reply"]
    body = await _chat(strict_client, _admin(ws), "give RMs the dashboard")
    assert not body["cards"] and "Only the Super Admin" in body["reply"]
