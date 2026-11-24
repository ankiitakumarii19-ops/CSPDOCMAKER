"""Each workspace's own connections (No. 210, Stage 3).

The rule that matters most: a workspace that is not Eko's never sees Eko's
sheet, mail account, WhatsApp or Zoho — its connections are blank until it
sets its own; passwords are kept locked and never shown or logged.
"""

import json
import uuid

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.models.enums import UserRole
from app.models.workspace_member import WorkspaceMember
from app.services import (assistant_tools, jwt_service, sheet_admin_service,
                          workspace_service, workspace_settings)
from app.workspace_context import all_workspaces, workspace

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER = "conn.owner@eko.co.in"
ADMIN = "conn.admin@eko.co.in"
EKO = uuid.UUID("00000000-0000-4000-8000-000000000001")
SHEET = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
LINK = f"https://docs.google.com/spreadsheets/d/{SHEET}/edit#gid=0"
PASSWORD = "very-secret-app-password-123"


@pytest.fixture(autouse=True)
def _fresh_redis_client(monkeypatch):
    monkeypatch.setattr(assistant_tools, "_redis", None)


@pytest.fixture(autouse=True)
def _eko_has_connections(monkeypatch):
    """The server's (Eko's) own connections, as on the server."""
    server = get_settings().server
    for key, value in (("google_sheets_csp_sheet_id", "EKO-SHEET-ID-0000000000000"),
                       ("smtp_host", "smtp.eko.example"),
                       ("smtp_username", "eko.sender@example.com"),
                       ("smtp_password", "eko-password"),
                       ("whatsapp_platform_url", "https://wa.eko.example/mcp"),
                       ("zoho_client_id", "eko-zoho")):
        monkeypatch.setattr(server, key, value)
    workspace_settings.forget()
    yield
    workspace_settings.forget()


@pytest.fixture
async def ws(migrated_db):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        created = await workspace_service.create_workspace(
            s, f"Conn Test {uuid.uuid4().hex[:6]}", OWNER, "Conn Owner")
        with all_workspaces():
            s.add(WorkspaceMember(workspace_id=created.id, email=ADMIN,
                                  role=UserRole.ADMIN, active=True))
        await s.commit()
        yield created
        with all_workspaces():
            await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                            .bindparams(w=created.id))
            await s.commit()


def _h(ws, email=OWNER, role="super_admin"):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": email, "email": email, "role": role,
        "name": email.split("@")[0], "ws": str(ws.id)})}


def _in(ws_id, key):
    with workspace(ws_id):
        return getattr(get_settings(), key)


async def test_a_new_workspace_never_sees_ekos_connections(strict_client, ws):
    for key in ("google_sheets_csp_sheet_id", "smtp_host", "smtp_username",
                "smtp_password", "whatsapp_platform_url", "zoho_client_id"):
        assert _in(ws.id, key) == "", key
        assert _in(EKO, key) == getattr(get_settings().server, key), key
    # Tab names are not Eko's data: they start as Eko's names.
    assert _in(ws.id, "google_sheets_csp_sheet_name") == \
        get_settings().server.google_sheets_csp_sheet_name
    body = (await strict_client.get("/api/admin/connections",
                                    headers=_h(ws))).json()
    assert body["workspace"]["eko"] is False
    assert not any(body["connected"].values())
    sheet = next(c for c in body["connections"]
                 if c["key"] == "google_sheets_csp_sheet_id")
    assert sheet["value"] == "" and not sheet["from_server"]


async def test_its_own_sheet_is_used_only_in_its_workspace(strict_client, ws):
    r = await strict_client.put(
        "/api/admin/connections/google_sheets_csp_sheet_id",
        json={"value": LINK}, headers=_h(ws))
    assert r.status_code == 200, r.text
    assert _in(ws.id, "google_sheets_csp_sheet_id") == SHEET
    assert _in(EKO, "google_sheets_csp_sheet_id") == "EKO-SHEET-ID-0000000000000"
    assert r.json()["connected"]["sheets"] is True
    r = await strict_client.put(
        "/api/admin/connections/google_sheets_csp_sheet_id",
        json={"value": "not a sheet"}, headers=_h(ws))
    assert r.status_code == 400 and "link" in r.json()["detail"]


async def test_a_password_is_locked_and_never_shown(strict_client, ws):
    from app.database import async_session_factory
    r = await strict_client.put("/api/admin/connections/smtp_password",
                                json={"value": PASSWORD}, headers=_h(ws))
    assert r.status_code == 200, r.text
    assert PASSWORD not in r.text
    item = next(c for c in r.json()["connections"]
                if c["key"] == "smtp_password")
    assert item["secret_set"] is True and item["value"] is None
    assert _in(ws.id, "smtp_password") == PASSWORD          # the code gets it
    async with async_session_factory() as s:
        with all_workspaces():
            stored = (await s.execute(text(
                "SELECT ciphertext FROM workspace_secrets WHERE "
                "workspace_id = :w").bindparams(w=ws.id))).scalar()
            logs = json.dumps([r[0] for r in (await s.execute(text(
                "SELECT metadata_json FROM audit_logs WHERE workspace_id = :w")
                .bindparams(w=ws.id))).all()])
            history = json.dumps([list(r) for r in (await s.execute(text(
                "SELECT old_value, new_value FROM workspace_setting_changes "
                "WHERE workspace_id = :w").bindparams(w=ws.id))).all()])
    assert stored and PASSWORD not in stored
    assert PASSWORD not in logs and PASSWORD not in history
    assert "(hidden)" in history
    r = await strict_client.delete("/api/admin/connections/smtp_password",
                                   headers=_h(ws))
    assert r.status_code == 200
    assert _in(ws.id, "smtp_password") == ""


async def test_a_changed_server_key_means_type_it_again(strict_client, ws,
                                                        monkeypatch):
    await strict_client.put("/api/admin/connections/smtp_password",
                            json={"value": PASSWORD}, headers=_h(ws))
    monkeypatch.setattr(get_settings().server, "app_secret_key",
                        "a-different-key")
    workspace_settings.forget()
    assert _in(ws.id, "smtp_password") == ""     # never someone else's


async def test_only_the_super_admin_sets_connections(strict_client, ws):
    r = await strict_client.get("/api/admin/connections",
                                headers=_h(ws, ADMIN, "admin"))
    assert r.status_code == 403


async def test_the_sheet_jobs_run_for_each_connected_workspace(strict_client,
                                                               ws):
    from app.workers import workspace_runner
    seen = []

    def probe():
        seen.append(get_settings().google_sheets_csp_sheet_id)
        return "ok"

    run = workspace_runner.for_configured_workspace(probe)
    run()
    assert seen == ["EKO-SHEET-ID-0000000000000"]        # Eko only, so far
    await strict_client.put(
        "/api/admin/connections/google_sheets_csp_sheet_id",
        json={"value": SHEET}, headers=_h(ws))
    seen.clear()
    run()
    assert sorted(seen) == sorted(["EKO-SHEET-ID-0000000000000", SHEET])


async def test_the_sheet_test_says_what_is_wrong(strict_client, ws,
                                                 monkeypatch):
    r = await strict_client.post("/api/admin/connections/test/sheets",
                                 headers=_h(ws))
    assert r.json() == {"ok": False, "message": "No main CSP sheet is set."}
    await strict_client.put(
        "/api/admin/connections/google_sheets_csp_sheet_id",
        json={"value": SHEET}, headers=_h(ws))
    monkeypatch.setattr(sheet_admin_service, "list_tabs",
                        lambda sid: [{"title": "Sheet1"}])
    r = await strict_client.post("/api/admin/connections/test/sheets",
                                 headers=_h(ws))
    body = r.json()
    assert body["ok"] is False and "no tab called 'KOData'" in body["message"]
    monkeypatch.setattr(sheet_admin_service, "list_tabs",
                        lambda sid: [{"title": "KOData"}, {"title": "INFO"}])
    r = await strict_client.post("/api/admin/connections/test/sheets",
                                 headers=_h(ws))
    assert r.json()["ok"] is True
    r = await strict_client.post("/api/admin/connections/test/email",
                                 headers=_h(ws))
    assert r.json()["ok"] is False and "mail server" in r.json()["message"]


async def test_zoho_tokens_are_kept_apart(monkeypatch):
    from app.services import zoho_client
    issued = []

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            issued.append(1)
            return {"access_token": f"tok{len(issued)}", "expires_in": 3600}

    monkeypatch.setattr(zoho_client.httpx, "post", lambda *a, **k: _Response())
    monkeypatch.setattr(zoho_client, "_token", None)
    monkeypatch.setattr(zoho_client, "_token_for", None)
    for key, value in (("zoho_client_secret", "s"), ("zoho_refresh_token", "r")):
        monkeypatch.setattr(get_settings().server, key, value)
    monkeypatch.setattr(get_settings().server, "zoho_client_id", "company-a")
    assert zoho_client.access_token() == "tok1"
    assert zoho_client.access_token() == "tok1"          # reused
    monkeypatch.setattr(get_settings().server, "zoho_client_id", "company-b")
    assert zoho_client.access_token() == "tok2"          # not company A's


# ---- by chat (ZU-03) ---------------------------------------------------------------

async def _chat(client, headers, question):
    r = await client.post("/api/assistant/chat", headers=headers,
                          json={"messages": [{"role": "user",
                                              "content": question}]})
    assert r.status_code == 200, r.text
    return r.json()


async def test_connecting_by_chat(strict_client, ws, monkeypatch):
    body = await _chat(strict_client, _h(ws), f"set csp sheet to {LINK}")
    [card] = body["cards"]
    assert card["kind"] == "change_connection"
    r = await strict_client.post(f"/api/assistant/actions/{card['id']}/run",
                                 headers=_h(ws))
    assert r.json()["ok"] is True, r.text
    assert _in(ws.id, "google_sheets_csp_sheet_id") == SHEET
    monkeypatch.setattr(sheet_admin_service, "list_tabs",
                        lambda sid: [{"title": "KOData"}])
    body = await _chat(strict_client, _h(ws), "test my sheet")
    assert "✅" in body["reply"] and "Main CSP sheet: opened" in body["reply"]


async def test_the_chat_never_takes_a_password(strict_client, ws):
    body = await _chat(strict_client, _h(ws),
                       "set smtp password to hunter2-secret")
    assert not body["cards"]
    assert "don't type a password" in body["reply"]
    assert _in(ws.id, "smtp_password") == ""
