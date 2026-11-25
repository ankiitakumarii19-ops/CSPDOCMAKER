"""
CSP DocMaker — Setup → Connections (PROJECT-REGISTER No. 210, Stage 3)

What the screen shows and saves, and its test buttons. Plain values go in
workspace_settings, passwords and keys in workspace_secrets (encrypted). A
secret is shown only as "set on … by …", never its value; the change
history says "set" / "removed", never the value.

Tests (each run inside the workspace, so they use ITS connection):
  sheets    open the main sheet and find its tabs (and the other sheets set)
  email     send a test email to the person who pressed the button
  whatsapp  ask the platform which tools it offers (sends nothing)
  crm       get a Zoho access token (reads nothing)
"""

import logging
from typing import Any, Optional

from app.services import connection_catalog as catalog
from app.services.connection_catalog import ConnectionError_

logger = logging.getLogger(__name__)
HIDDEN = "(hidden)"



def _neutral(text):
    """No. 247: Eko's own examples are not shown to another workspace."""
    from app.services import org_identity
    return org_identity.neutral(text)

def _who(user: dict) -> str:
    return ((user or {}).get("sub") or (user or {}).get("email") or "").lower()


async def _workspace(session):
    from app.services.workspace_settings import _workspace as ws
    return await ws(session)


def _is_eko(ws) -> bool:
    from app.services.workspace_settings import EKO_WORKSPACE
    return ws is not None and ws.id == EKO_WORKSPACE


def _connection(key: str):
    c = catalog.BY_KEY.get(key)
    if c is None:
        raise ConnectionError_(f"There is no connection setting {key!r}.")
    return c


async def describe(session) -> dict:
    from sqlalchemy import select
    from app.config import get_settings
    from app.models.workspace_setting import WorkspaceSecret, WorkspaceSetting
    from app.services import workspace_setup
    ws = await _workspace(session)
    eko = _is_eko(ws)
    rows = {r.key: r for r in (await session.execute(select(
        WorkspaceSetting).where(WorkspaceSetting.key.in_(
            sorted(catalog.KEYS))))).scalars()}
    secrets = {r.key: r for r in (await session.execute(
        select(WorkspaceSecret))).scalars()}
    server = get_settings().server
    items = []
    for c in catalog.CONNECTIONS:
        if c.kind == catalog.SECRET:
            row = secrets.get(c.key)
            from_server = row is None and eko and bool(getattr(server, c.key, ""))
            items.append({
                "key": c.key, "group": c.group, "label": c.label,
                "help": _neutral(c.help), "kind": c.kind, "choices": list(c.choices),
                "value": None, "secret_set": row is not None or from_server,
                "own": row is not None, "from_server": from_server,
                "changed_by": row.updated_by if row else None,
                "changed_at": row.updated_at.isoformat() if row and row.updated_at else None})
            continue
        row = rows.get(c.key)
        if row is not None:
            value, own = row.value, True
        elif eko or not c.eko_only:
            value, own = getattr(server, c.key, catalog.blank(c)), False
        else:
            value, own = catalog.blank(c), False
        items.append({
            "key": c.key, "group": c.group, "label": c.label, "help": _neutral(c.help),
            "kind": c.kind, "choices": list(c.choices), "value": value,
            "own": own, "from_server": not own and eko and c.eko_only
            and bool(value),
            "changed_by": row.updated_by if row else None,
            "changed_at": row.updated_at.isoformat() if row and row.updated_at else None})
    return {
        "workspace": {"id": str(ws.id), "name": ws.name, "eko": eko},
        "groups": [{"key": k, "title": t, "about": a}
                   for k, t, a in catalog.GROUPS],
        "connections": items,
        "robot_email": workspace_setup.service_account_email(),
        "connected": {g: _group_connected(g, items) for g in catalog.GROUP_KEYS},
        "note": ("Eko's workspace uses the server's connections until you "
                 "set its own here." if eko else
                 "Nothing of Eko's is used here: each connection is blank "
                 "until you set your own."),
    }


def _group_connected(group: str, items) -> bool:
    by = {i["key"]: i for i in items}
    need = {"sheets": ["google_sheets_csp_sheet_id"],
            "email": ["smtp_host", "smtp_username", "smtp_password"],
            "whatsapp": ["whatsapp_platform_url"],
            "crm": ["zoho_client_id", "zoho_client_secret",
                    "zoho_refresh_token"]}[group]
    return all((by[k].get("secret_set") if by[k]["kind"] == catalog.SECRET
                else bool(by[k]["value"])) for k in need)


async def set_value(session, key: str, raw: Any, user,
                    via: str = "screen") -> None:
    from sqlalchemy import select
    from app.models.workspace_setting import WorkspaceSecret, WorkspaceSetting
    from app.services import secret_store, workspace_settings
    c = _connection(key)
    ws = await _workspace(session)
    if c.kind == catalog.SECRET:
        plain = str(raw or "")
        if not plain.strip():
            raise ConnectionError_(f"{c.label}: type it, or use Remove.")
        if len(plain) > 2000:
            raise ConnectionError_(f"{c.label} is too long.")
        row = (await session.execute(select(WorkspaceSecret).where(
            WorkspaceSecret.key == key))).scalars().first()
        old = HIDDEN if row is not None else None
        token = secret_store.lock(plain)
        if row is None:
            session.add(WorkspaceSecret(workspace_id=ws.id, key=key,
                                        ciphertext=token,
                                        updated_by=_who(user)))
        else:
            row.ciphertext, row.updated_by = token, _who(user)
        await workspace_settings._record(session, ws, f"connection:{key}",
                                         old, HIDDEN, user, via)
    else:
        value = catalog.parse(c, raw)
        row = (await session.execute(select(WorkspaceSetting).where(
            WorkspaceSetting.key == key))).scalars().first()
        old = row.value if row is not None else None
        if row is not None and row.value == value:
            return
        if row is None:
            session.add(WorkspaceSetting(workspace_id=ws.id, key=key,
                                         value=value, updated_by=_who(user)))
        else:
            row.value, row.updated_by = value, _who(user)
        await workspace_settings._record(session, ws, f"connection:{key}",
                                         old, value, user, via)
    await session.commit()
    workspace_settings.forget(ws.id)
    logger.info("connections: %s set %s in %s (%s)", _who(user), key,
                ws.slug, via)


async def clear(session, key: str, user) -> None:
    """Remove this workspace's own value: Eko falls back to the server's,
    any other workspace is not connected."""
    from sqlalchemy import delete
    from app.models.workspace_setting import WorkspaceSecret, WorkspaceSetting
    from app.services import workspace_settings
    c = _connection(key)
    ws = await _workspace(session)
    model = WorkspaceSecret if c.kind == catalog.SECRET else WorkspaceSetting
    result = await session.execute(delete(model).where(
        model.workspace_id == ws.id, model.key == key))
    if not result.rowcount:
        return
    await workspace_settings._record(
        session, ws, f"connection:{key}",
        HIDDEN if c.kind == catalog.SECRET else "(was set)", None, user,
        "screen")
    await session.commit()
    workspace_settings.forget(ws.id)


# ---- tests ------------------------------------------------------------------

def _ok(message: str) -> dict:
    return {"ok": True, "message": message}


def _bad(message: str) -> dict:
    return {"ok": False, "message": message}


def test_sheets() -> dict:
    from app.config import get_settings
    from app.services import sheet_admin_service as sheets
    s = get_settings()
    if not s.google_sheets_csp_sheet_id:
        return _bad("No main CSP sheet is set.")
    lines, ok = [], True
    for label, sid, tabs in (
            ("Main CSP sheet", s.google_sheets_csp_sheet_id,
             [s.google_sheets_csp_sheet_name]),
            ("Sign-in list sheet", s.google_sheets_id, []),
            ("Old records sheet", s.calling_sheet_id, [s.calling_sheet_tab]),
            ("New records sheet", s.lead_sheet_id, [s.lead_sheet_tab]),
            ("Address sheet", s.address_sheet_id, [])):
        if not sid:
            continue
        try:
            found = {t["title"] for t in sheets.list_tabs(sid)}
        except Exception as e:
            ok = False
            lines.append(f"{label}: cannot open it — {type(e).__name__}: "
                         f"{str(e)[:200]}. Share it with the robot address "
                         "as an editor.")
            continue
        missing = [t for t in tabs if t and t not in found]
        if missing:
            ok = False
            lines.append(f"{label}: opened, but no tab called "
                         + ", ".join(repr(t) for t in missing)
                         + f" (tabs: {', '.join(sorted(found)[:12])}).")
        else:
            lines.append(f"{label}: opened ({len(found)} tabs).")
    return {"ok": ok, "message": " ".join(lines)}


def test_email(to: str) -> dict:
    from app.config import get_settings
    from app.services import email_service
    s = get_settings()
    if not (s.smtp_host and s.smtp_username and s.smtp_password):
        return _bad("Set the mail server, sign-in address and password first.")
    if email_service.paused():
        return _bad("Emails are paused (Settings → Email); the test was not "
                    "sent.")
    try:
        sent = email_service._send_via_smtp(
            to, "CSPdocMaker: test email",
            "<p>This test email shows the connection works.</p>",
            "This test email shows the connection works.")
    except Exception as e:
        return _bad(f"Could not send: {type(e).__name__}: {str(e)[:300]}")
    return (_ok(f"Sent a test email to {to} from "
                f"{s.smtp_from_email or s.smtp_username}.") if sent else
            _bad("The mail server refused it — see the app log (check the "
                 "address, password and port)."))


def test_whatsapp() -> dict:
    from app.config import get_settings
    from app.services import whatsapp_platform
    if not get_settings().whatsapp_platform_url:
        return _bad("No WhatsApp platform address is set.")
    try:
        result = whatsapp_platform._rpc("tools/list", {})
    except Exception as e:
        return _bad(f"Could not reach it: {str(e)[:300]}")
    tools = (result.get("result") or {}).get("tools") or []
    return _ok(f"The platform answered ({len(tools)} tools). Nothing was "
               "sent.")


def test_crm() -> dict:
    from app.services import zoho_client
    if not zoho_client.is_configured():
        return _bad("Set the Zoho client id, secret and refresh token first.")
    try:
        zoho_client.access_token(force=True)
    except Exception as e:
        return _bad(f"Zoho refused: {str(e)[:300]}")
    return _ok("Zoho gave an access token. Nothing was read.")


async def run_test(group: str, user) -> dict:
    import asyncio
    if group not in catalog.GROUP_KEYS:
        raise ConnectionError_(f"There is no connection group {group!r}.")
    fn = {"sheets": test_sheets, "whatsapp": test_whatsapp,
          "crm": test_crm}.get(group)
    loop = asyncio.get_running_loop()
    from app.workspace_context import current_workspace_id, workspace
    wid = current_workspace_id()

    def inside():
        with workspace(wid):
            return fn() if fn else test_email(_who(user))
    out = await loop.run_in_executor(None, inside)
    logger.info("connections: test %s -> %s", group,
                "ok" if out["ok"] else "failed")
    return out
