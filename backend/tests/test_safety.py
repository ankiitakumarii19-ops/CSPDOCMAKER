"""Safety between workspaces and the go-live safety checks (No. 216, Stage 9).

The isolation test: one workspace's data is put in place, then EVERY list
route of the app is called as another workspace's Super Admin; none may
show it.
"""

import io
import uuid
import zipfile

import pytest
from sqlalchemy import text

from app.models.csp_record import CSPRecord
from app.models.email_message import EmailMessage
from app.services import (jwt_service, settings_catalog, sheet_admin_service,
                          workspace_service, workspace_settings)
from app.workspace_context import all_workspaces, workspace

pytestmark = pytest.mark.asyncio(loop_scope="session")

MARK = "ZQXLEAKMARKER"


async def _ws(owner):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        ws = await workspace_service.create_workspace(
            s, f"Safety {uuid.uuid4().hex[:6]}", owner, "Owner")
        await s.commit()
        return ws


async def _drop(*wss):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with all_workspaces():
            for ws in wss:
                await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                                .bindparams(w=ws.id))
            await s.commit()
    workspace_settings.forget()


def _h(ws, owner):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": owner, "email": owner, "role": "super_admin", "name": "O",
        "ws": str(ws.id)})}


async def test_no_list_route_shows_another_workspaces_data(strict_client,
                                                           migrated_db,
                                                           monkeypatch):
    from fastapi.routing import APIRoute
    from app.database import async_session_factory
    from app.main import app

    def no_google(*a, **k):
        raise sheet_admin_service.SheetAdminError("no Google in tests")
    for name in ("list_tabs", "_header", "read_tab", "describe"):
        monkeypatch.setattr(sheet_admin_service, name, no_google)

    a_owner, b_owner = "safety.a@eko.co.in", "safety.b@eko.co.in"
    a, b = await _ws(a_owner), await _ws(b_owner)
    try:
        async with async_session_factory() as s:
            with workspace(a.id):
                s.add(CSPRecord(csp_id=f"{MARK}1", csp_code=f"{MARK}1",
                                name=f"{MARK} Person", origin="new",
                                rm_resolution="unresolved"))
                s.add(EmailMessage(to_email=f"{MARK.lower()}@example.com",
                                   kind="other", subject=f"{MARK} subject",
                                   track_token=uuid.uuid4().hex,
                                   send_status="sent"))
                await s.commit()
        # A sees its own data (the marker is findable at all) …
        r = await strict_client.get("/api/admin/database",
                                    headers=_h(a, a_owner))
        assert MARK in r.text
        # … and B sees none of it, on any list route.
        checked, leaks = 0, []
        for route in app.routes:
            if (not isinstance(route, APIRoute) or "GET" not in route.methods
                    or "{" in route.path or not route.path.startswith("/api/")
                    or route.path.startswith(("/api/auth", "/api/health"))):
                continue
            r = await strict_client.get(route.path, headers=_h(b, b_owner))
            checked += 1
            if MARK in r.text or MARK.lower() in r.text:
                leaks.append(route.path)
        assert checked > 40
        assert not leaks, f"another workspace's data shown on: {leaks}"
    finally:
        await _drop(a, b)


async def test_export_is_own_data_without_secrets(strict_client, migrated_db):
    owner = "safety.x@eko.co.in"
    ws = await _ws(owner)
    try:
        await strict_client.put("/api/admin/connections/smtp_password",
                                json={"value": "pw-never-exported"},
                                headers=_h(ws, owner))
        r = await strict_client.get("/api/admin/workspace/export",
                                    headers=_h(ws, owner))
        assert r.status_code == 200
        z = zipfile.ZipFile(io.BytesIO(r.content))
        assert "records.csv" in z.namelist()
        everything = b"".join(z.read(n) for n in z.namelist())
        assert b"pw-never-exported" not in everything
        assert b"token_hash" not in everything
    finally:
        await _drop(ws)


async def test_closing_a_workspace(strict_client, migrated_db):
    owner = "safety.c@eko.co.in"
    ws = await _ws(owner)
    try:
        r = await strict_client.post("/api/admin/workspace/close",
                                     json={"confirm": "wrong"},
                                     headers=_h(ws, owner))
        assert r.status_code == 400
        r = await strict_client.post("/api/admin/workspace/close",
                                     json={"confirm": ws.name},
                                     headers=_h(ws, owner))
        assert r.json()["closed"] is True
    finally:
        await _drop(ws)
    eko = {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": "super_admin@eko.co.in", "email": "super_admin@eko.co.in",
        "role": "super_admin", "name": "S"})}
    from app.main import app  # noqa: F401 — the Eko workspace is the default
    r = await strict_client.post("/api/admin/workspace/close",
                                 json={"confirm": "Eko SBI Kiosk CSP"},
                                 headers=eko)
    assert r.status_code in (400, 403)


def test_safety_rules_that_no_setting_can_switch_off():
    keys = " ".join(settings_catalog.KEYS)
    # the change history and isolation are not settings
    for word in ("history", "audit", "isolation", "workspace_id"):
        assert word not in keys
    # every ceiling a wrong setting could break is bounded
    for key in ("verify_batch_size", "resend_failed_batch",
                "contact_loop_batch", "reply_auto_per_day"):
        assert settings_catalog.BY_KEY[key].max is not None
