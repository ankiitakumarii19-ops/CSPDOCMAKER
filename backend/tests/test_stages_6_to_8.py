"""Messages (No. 213), jobs / alerts / weekly email / look (No. 214), and
going live / test mode / pause all (No. 215) — each a workspace's own, Eko's
unchanged when nothing is set."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import UserRole
from app.models.workspace_member import WorkspaceMember
from app.services import (csp_replies, email_service, jwt_service, send_guard,
                          weekly_health, whatsapp_platform, workspace_service,
                          workspace_settings)
from app.workspace_context import all_workspaces, workspace

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER = "s68.owner@eko.co.in"
EKO = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
async def ws(migrated_db):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        created = await workspace_service.create_workspace(
            s, f"S68 Test {uuid.uuid4().hex[:6]}", OWNER, "S68 Owner")
        await s.commit()
        yield created
        with all_workspaces():
            await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                            .bindparams(w=created.id))
            await s.commit()
    workspace_settings.forget()


def _h(ws):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": OWNER, "email": OWNER, "role": "super_admin",
        "name": "Owner", "ws": str(ws.id)})}


async def _set(client, ws, key, value):
    r = await client.put(f"/api/admin/settings/{key}", json={"value": value},
                         headers=_h(ws))
    assert r.status_code == 200, (key, r.text)


def _sync():
    return create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))


# ---- Stage 6: sending days, holidays, daily limit, own words ----------------------

async def test_sending_days_and_holidays(strict_client, ws):
    from app.workers.verify_old_csps_worker import in_hours
    noon_monday = datetime(2026, 11, 23, 6, 30, tzinfo=timezone.utc)  # 12:00 IST
    with workspace(ws.id):
        assert in_hours(noon_monday, 8, 20) is True
    await _set(strict_client, ws, "send_days", "tue,wed,thu,fri")
    with workspace(ws.id):
        assert in_hours(noon_monday, 8, 20) is False
    await _set(strict_client, ws, "send_days", "mon")
    await _set(strict_client, ws, "send_holidays", "2026-11-23")
    with workspace(ws.id):
        assert in_hours(noon_monday, 8, 20) is False
    with workspace(EKO):
        assert in_hours(noon_monday, 8, 20) is True
    r = await strict_client.put("/api/admin/settings/send_holidays",
                                json={"value": "25 Dec"}, headers=_h(ws))
    assert r.status_code == 400 and "not a date" in r.json()["detail"]


async def test_the_daily_limit_per_number(strict_client, ws, monkeypatch):
    await _set(strict_client, ws, "workspace_live", True)
    await _set(strict_client, ws, "send_max_per_person_day", 2)
    engine = _sync()
    with Session(engine) as s, all_workspaces():
        for _ in range(2):
            s.execute(text(
                "INSERT INTO whatsapp_messages (id, workspace_id, phone, kind,"
                " is_test, send_status, source, sent_at) VALUES (:i, :w, "
                "'919812300009', 'other', false, 'sent', 'test', now())"),
                {"i": str(uuid.uuid4()), "w": str(ws.id)})
        s.commit()
    engine.dispose()
    monkeypatch.setattr(whatsapp_platform, "call_tool",
                        lambda *a, **k: pytest.fail("must not be sent"))
    monkeypatch.setattr(get_settings().server, "test_copy", False)
    with workspace(ws.id):
        out = whatsapp_platform.send("9812300009", "Hi {name}", {"name": "A"},
                                     source_name="test")
    assert out["status"] == "failed" and "2 message(s) already" in out["reason"]


async def test_own_never_answer_words(strict_client, ws):
    with workspace(ws.id):
        assert csp_replies.is_technical("my gst number is wrong") is False
    await _set(strict_client, ws, "reply_never_answer_words", "gst, tax")
    with workspace(ws.id):
        assert csp_replies.is_technical("my gst number is wrong") is True
    with workspace(EKO):
        assert csp_replies.is_technical("my gst number is wrong") is False


# ---- Stage 7: jobs, alerts, weekly email, look ------------------------------------

async def test_a_job_switched_off_or_paced_for_one_workspace(strict_client, ws):
    from app.workers import workspace_runner
    ran = []

    def sync_csp_data():          # the name the runner knows the job by
        from app.workspace_context import current_workspace_id
        ran.append(current_workspace_id())
        return "ok"

    run = workspace_runner.for_each_workspace(sync_csp_data)
    key = f"cspdm:job:{ws.id}:sheet_read"
    workspace_runner._redis().delete(key)
    run()
    assert ws.id in ran
    await _set(strict_client, ws, "job_sheet_read_on", False)
    ran.clear()
    out = run()
    assert ws.id not in ran and EKO in ran
    assert any(r["result"] == {"skipped": "switched off for this workspace "
                               "(Settings → Background jobs)"}
               for r in out["results"])
    await _set(strict_client, ws, "job_sheet_read_on", True)
    await _set(strict_client, ws, "job_sheet_read_every", 60)
    workspace_runner._redis().delete(key)
    ran.clear()
    run()
    run()
    assert ran.count(ws.id) == 1          # the second was not due
    workspace_runner._redis().delete(key)


async def test_alerts_go_to_the_workspaces_own_list(strict_client, ws):
    from app.services import alerts
    await _set(strict_client, ws, "alert_to", "ops@example.com, lead@example.com")
    engine = _sync()
    with Session(engine) as s, workspace(ws.id):
        assert alerts.recipients(s) == ["lead@example.com", "ops@example.com"]
    engine.dispose()


async def test_the_weekly_email_with_what_to_fix(strict_client, ws, monkeypatch):
    from app.services import message_sender
    monkeypatch.setattr(message_sender, "link_is_reachable", lambda url: True)
    monkeypatch.setattr(get_settings().server, "test_copy", False)
    monday_9 = datetime(2026, 11, 23, 3, 45, tzinfo=timezone.utc)  # 09:15 IST
    sent = []
    engine = _sync()
    with Session(engine) as s, workspace(ws.id):
        out = weekly_health.run(s, now=monday_9,
                                send=lambda to, sub, body: (sent.append(
                                    (to, sub, body)) or (True, "")))
        assert out["sent_to"] == [OWNER]
        body = sent[0][2]
        assert "What to fix in your setup:" in body
        assert "No main CSP sheet is connected" in body
        again = weekly_health.run(s, now=monday_9, send=lambda *a: (True, ""))
        assert again == {"skipped": "already sent this week"}
        tuesday = datetime(2026, 11, 24, 3, 45, tzinfo=timezone.utc)
        assert weekly_health.due(s, tuesday) == "not the day and hour"
    engine.dispose()


async def test_the_apps_own_name_and_colour(strict_client, ws):
    await _set(strict_client, ws, "brand_name", "Kiosk Docs")
    await _set(strict_client, ws, "brand_color", "#1E40AF")
    me = (await strict_client.get("/api/me/access", headers=_h(ws))).json()
    assert me["look"] == {"name": "Kiosk Docs", "color": "#1E40AF"}
    r = await strict_client.put("/api/admin/settings/brand_color",
                                json={"value": "blue"}, headers=_h(ws))
    assert r.status_code == 400


# ---- Stage 8: live, test mode, pause all, go live, dry run ------------------------

async def test_a_new_workspace_sends_nothing_until_it_goes_live(strict_client, ws):
    with workspace(ws.id):
        assert "not live yet" in send_guard.refusal()
        assert email_service.paused() is True
        number, why = send_guard.whatsapp_to("9812300001")
        assert number is None and "not live" in why
    with workspace(EKO):
        assert send_guard.refusal() is None          # Eko: live, as today
    r = await strict_client.post("/api/admin/setup-guide/go-live",
                                 headers=_h(ws))
    assert r.status_code == 400 and "finish these first" in r.json()["detail"]
    guide = (await strict_client.get("/api/admin/setup-guide",
                                     headers=_h(ws))).json()
    assert guide["live"] is False and guide["ready_to_go_live"] is False
    assert any(s["where"] == "connections" for s in guide["steps"])


async def test_test_mode_sends_only_to_the_test_number(strict_client, ws):
    r = await strict_client.put("/api/admin/settings/test_mode",
                                json={"value": True}, headers=_h(ws))
    assert r.status_code == 400 and "test WhatsApp number" in r.json()["detail"]
    await _set(strict_client, ws, "test_mode_phone", "9812300077")
    await _set(strict_client, ws, "test_mode_email", "me@example.com")
    await _set(strict_client, ws, "test_mode", True)
    with workspace(ws.id):
        assert send_guard.whatsapp_to("9812300001") == ("9812300077", None)
        assert send_guard.email_to("csp@example.com") == "me@example.com"
        assert email_service.paused() is False
    await _set(strict_client, ws, "pause_all", True)
    with workspace(ws.id):
        assert "paused" in send_guard.refusal()


async def test_the_dry_run_sends_nothing(strict_client, ws):
    r = await strict_client.post("/api/admin/setup-guide/dry-run",
                                 headers=_h(ws))
    assert r.status_code == 200, r.text
    assert r.json()["sent"] == 0 and r.json()["records"] == []
