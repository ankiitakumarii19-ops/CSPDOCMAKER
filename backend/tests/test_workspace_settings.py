"""Settings centre: each workspace's own settings (No. 204, Stage 1).

Every test runs in a fresh workspace made the way sign-up makes one, so
Eko's workspace is never changed — and the tests check it stays on the
server's (Eko's) values while the new workspace changes its own.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.models.enums import UserRole
from app.models.workspace_member import WorkspaceMember
from app.services import (assistant_tools, jwt_service, settings_catalog,
                          workspace_service, workspace_settings)
from app.workspace_context import all_workspaces, workspace

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER = "settings.owner@eko.co.in"
ADMIN = "settings.admin@eko.co.in"
EKO = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture(autouse=True)
def _fresh_redis_client(monkeypatch):
    monkeypatch.setattr(assistant_tools, "_redis", None)


@pytest.fixture
async def ws(migrated_db):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        created = await workspace_service.create_workspace(
            s, f"Settings Test {uuid.uuid4().hex[:6]}", OWNER, "Settings Owner")
        with all_workspaces():
            s.add(WorkspaceMember(workspace_id=created.id, email=ADMIN,
                                  role=UserRole.ADMIN, active=True))
        await s.commit()
        yield created
        with all_workspaces():
            await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                            .bindparams(w=created.id))
            await s.commit()
    workspace_settings.forget()


def _h(ws, email=OWNER, role="super_admin"):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": email, "email": email, "role": role,
        "name": email.split("@")[0], "ws": str(ws.id)})}


def _admin(ws):
    return _h(ws, ADMIN, "admin")


def _value(ws_id, key):
    with workspace(ws_id):
        return getattr(get_settings(), key)


# ---- Eko keeps its values; a workspace changes only its own ---------------

async def test_a_new_workspace_starts_with_the_standard_values(strict_client, ws):
    r = await strict_client.get("/api/admin/settings", headers=_h(ws))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["settings"]) == len(settings_catalog.SETTINGS)
    for s in body["settings"]:
        assert s["value"] == s["standard"] and not s["changed"], s["key"]
        assert s["can_change"] is True
    assert {g["key"] for g in body["groups"]} == set(settings_catalog.GROUP_KEYS)


async def test_a_change_reaches_the_code_in_that_workspace_only(strict_client, ws):
    server = get_settings().server.documents_feedback_after_minutes
    r = await strict_client.put(
        "/api/admin/settings/documents_feedback_after_minutes",
        json={"value": 45}, headers=_h(ws))
    assert r.status_code == 200, r.text
    assert r.json()["value"] == 45 and r.json()["changed"] is True
    assert _value(ws.id, "documents_feedback_after_minutes") == 45
    assert _value(EKO, "documents_feedback_after_minutes") == server
    assert get_settings().server.documents_feedback_after_minutes == server


async def test_a_value_outside_its_safe_range_is_refused(strict_client, ws):
    r = await strict_client.put("/api/admin/settings/verify_batch_size",
                                json={"value": 5000}, headers=_h(ws))
    assert r.status_code == 400
    assert "from 1 to 200" in r.json()["detail"]
    r = await strict_client.put("/api/admin/settings/emails_paused",
                                json={"value": "maybe"}, headers=_h(ws))
    assert r.status_code == 400 and "on or off" in r.json()["detail"]
    r = await strict_client.put("/api/admin/settings/database_password",
                                json={"value": "x"}, headers=_h(ws))
    assert r.status_code == 400 and "no setting" in r.json()["detail"]


async def test_messages_must_start_before_they_stop(strict_client, ws):
    start = get_settings().server.verify_start_hour
    r = await strict_client.put("/api/admin/settings/verify_end_hour",
                                json={"value": start}, headers=_h(ws))
    assert r.status_code == 400
    assert "start before they stop" in r.json()["detail"]


async def test_every_change_is_in_the_history_and_can_be_undone(strict_client, ws):
    standard = get_settings().server.reply_auto_per_day
    h = _h(ws)
    for n in (5, 7):
        r = await strict_client.put("/api/admin/settings/reply_auto_per_day",
                                    json={"value": n}, headers=h)
        assert r.status_code == 200, r.text
    changes = (await strict_client.get(
        "/api/admin/settings/history?key=reply_auto_per_day",
        headers=h)).json()["changes"]
    assert [(c["before"], c["after"]) for c in changes] == [
        ("5 replies", "7 replies"), ("standard value", "5 replies")]
    assert changes[0]["by"] == OWNER and changes[0]["via"] == "screen"

    r = await strict_client.post(
        f"/api/admin/settings/history/{changes[0]['id']}/undo", headers=h)
    assert r.status_code == 200 and r.json()["value"] == 5
    r = await strict_client.post(
        f"/api/admin/settings/history/{changes[1]['id']}/undo", headers=h)
    assert r.json()["value"] == standard and r.json()["own"] is False
    assert _value(ws.id, "reply_auto_per_day") == standard
    latest = (await strict_client.get("/api/admin/settings/history",
                                      headers=h)).json()["changes"][0]
    assert latest["via"] == "undo" and latest["after"] == "standard value"


async def test_back_to_the_standard_value(strict_client, ws):
    h = _h(ws)
    await strict_client.put("/api/admin/settings/alerts_enabled",
                            json={"value": False}, headers=h)
    assert _value(ws.id, "alerts_enabled") is False
    r = await strict_client.delete("/api/admin/settings/alerts_enabled",
                                   headers=h)
    assert r.status_code == 200 and r.json()["own"] is False
    assert _value(ws.id, "alerts_enabled") == get_settings().server.alerts_enabled


async def test_admins_change_only_the_groups_handed_to_them(strict_client, ws):
    r = await strict_client.put(
        "/api/admin/settings/documents_feedback_enabled",
        json={"value": False}, headers=_admin(ws))
    assert r.status_code == 403
    r = await strict_client.put("/api/admin/settings/admin-groups",
                                json={"groups": ["feedback"]},
                                headers=_admin(ws))
    assert r.status_code == 403
    r = await strict_client.put("/api/admin/settings/admin-groups",
                                json={"groups": ["feedback"]}, headers=_h(ws))
    assert r.status_code == 200 and r.json() == {"admin_groups": ["feedback"]}

    body = (await strict_client.get("/api/admin/settings",
                                    headers=_admin(ws))).json()
    can = {s["key"]: s["can_change"] for s in body["settings"]}
    assert can["documents_feedback_enabled"] and not can["alerts_enabled"]
    r = await strict_client.put(
        "/api/admin/settings/documents_feedback_enabled",
        json={"value": False}, headers=_admin(ws))
    assert r.status_code == 200, r.text
    r = await strict_client.put("/api/admin/settings/alerts_enabled",
                                json={"value": False}, headers=_admin(ws))
    assert r.status_code == 403


async def test_rms_do_not_see_the_settings(strict_client, ws):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with all_workspaces():
            s.add(WorkspaceMember(workspace_id=ws.id,
                                  email="settings.rm@eko.co.in",
                                  role=UserRole.RM, active=True))
            await s.commit()
    r = await strict_client.get("/api/admin/settings", headers=_h(
        ws, "settings.rm@eko.co.in", "rm"))
    assert r.status_code == 403


# ---- the code reads the workspace's value -----------------------------------------

async def test_the_moved_rules_follow_the_workspace(strict_client, ws):
    from app.services import csp_replies, feedback_loops, resend_failed
    from app.workers.verify_old_csps_worker import in_hours
    h = _h(ws)
    for key, value in (("send_time_zone", "+00:00"),
                       ("resend_first_wait_minutes", 10),
                       ("resend_longest_wait_hours", 1),
                       ("reply_auto_per_day", 9),
                       ("contact_fix_max_tries", 6)):
        r = await strict_client.put(f"/api/admin/settings/{key}",
                                    json={"value": value}, headers=h)
        assert r.status_code == 200, (key, r.text)
    six_utc = datetime(2026, 11, 23, 6, 0, tzinfo=timezone.utc)  # 11:30 IST
    with workspace(ws.id):
        assert in_hours(six_utc, 8, 20) is False        # 06:00 on its clock
        assert resend_failed.wait(1).total_seconds() == 600
        assert resend_failed.wait(9).total_seconds() == 3600
        assert csp_replies._auto_per_day() == 9
        assert feedback_loops._max_tries() == 6
    with workspace(EKO):
        assert in_hours(six_utc, 8, 20) is True         # 11:30 in India
        assert resend_failed.wait(1).total_seconds() == 1800
        assert csp_replies._auto_per_day() == 3


async def test_values_already_read_are_kept_if_the_database_cannot_be_read(
        strict_client, ws, monkeypatch):
    await strict_client.put("/api/admin/settings/verify_batch_size",
                            json={"value": 40}, headers=_h(ws))
    workspace_settings.forget()
    assert _value(ws.id, "verify_batch_size") == 40
    monkeypatch.setattr(workspace_settings, "CACHE_SECONDS", 0)
    monkeypatch.setattr(workspace_settings, "_read", lambda w: None)
    assert _value(ws.id, "verify_batch_size") == 40


# ---- by chat (ZU-01) ----------------------------------------------------------------

async def _chat(client, ws, question, headers=None):
    r = await client.post("/api/assistant/chat", headers=headers or _h(ws),
                          json={"messages": [{"role": "user",
                                              "content": question}]})
    assert r.status_code == 200, r.text
    return r.json()


async def test_the_chat_proposes_a_change_and_do_it_saves_it(strict_client, ws):
    body = await _chat(strict_client, ws, "set feedback delay to 30 minutes")
    [card] = body["cards"]
    assert card["type"] == "action" and card["kind"] == "change_setting"
    assert "→ new: 30 minutes" in card["detail"]
    assert _value(ws.id, "documents_feedback_after_minutes") == \
        get_settings().server.documents_feedback_after_minutes   # not yet
    r = await strict_client.post(f"/api/assistant/actions/{card['id']}/run",
                                 headers=_h(ws))
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert _value(ws.id, "documents_feedback_after_minutes") == 30
    change = (await strict_client.get("/api/admin/settings/history",
                                      headers=_h(ws))).json()["changes"][0]
    assert change["via"] == "chat" and change["after"] == "30 minutes"


async def test_the_chat_says_why_it_cannot(strict_client, ws):
    body = await _chat(strict_client, ws, "set form link to 99 days")
    assert not body["cards"] and "from 1 to 30" in body["reply"]
    body = await _chat(strict_client, ws, "set wobble setting to 3")
    assert "don't know a setting" in body["reply"]
    body = await _chat(strict_client, ws, "set feedback delay to 30",
                       headers=_admin(ws))
    assert not body["cards"] and "Only the Super Admin" in body["reply"]
