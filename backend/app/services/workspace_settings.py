"""
CSP DocMaker — reading and changing a workspace's own settings
(PROJECT-REGISTER No. 204, Stage 1: Settings centre, TK-007 / TK-008 / TK-013)

Reading (any code, any process): get_settings().<key> inside a workspace
asks own_value() here. The workspace's values are read from the database
and kept for CACHE_SECONDS, so a change made on the screen reaches this
process at once and the background workers within half a minute.

If the values cannot be read (database down), the last values read are
kept and the failure is logged as an error — never silently switched back
to the standard values while the database is merely slow.

Changing (the Settings screen, the chat's Do it, undo): set_value(),
to_standard(), undo(). Each one checks the value against its safe range
and the rules between settings, writes the change history and the audit
log, and is refused with a plain reason otherwise.

Who may change: the Super Admin always; an Admin only the groups the Super
Admin handed to Admins (kept in Workspace.settings["settings_admin_groups"]).
"""

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from app.services import settings_catalog as catalog
from app.services.settings_catalog import SettingError

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30
ADMIN_GROUPS_KEY = "settings_admin_groups"


class _Missing:
    def __repr__(self):
        return "MISSING"


MISSING = _Missing()

_cache: Dict[uuid.UUID, tuple] = {}     # workspace -> (read at, values)
_lock = threading.Lock()
_last_error_logged = 0.0


# ---- reading --------------------------------------------------------------

# No. 215: what a workspace other than Eko's starts with, where it is not
# the server's (Eko's) value — a new workspace is not live until it goes live.
NOT_EKO_DEFAULTS = {"workspace_live": False}

# Eko's workspace: the one the server's own connections (.env) belong to.
EKO_WORKSPACE = uuid.UUID("00000000-0000-4000-8000-000000000001")


def own_value(key: str) -> Any:
    """This workspace's own value for `key`, or MISSING (use the server's).

    A connection marked eko_only (connection_catalog) answers blank in any
    workspace but Eko's until that workspace connects its own — so no other
    workspace ever reads Eko's sheet or sends from Eko's account."""
    from app.workspace_context import current_workspace_id
    workspace_id = current_workspace_id()
    if workspace_id is None:
        return MISSING
    value = values_for(workspace_id).get(key, MISSING)
    if value is MISSING and workspace_id != EKO_WORKSPACE:
        if key in NOT_EKO_DEFAULTS:
            return NOT_EKO_DEFAULTS[key]
        from app.services import connection_catalog
        c = connection_catalog.BY_KEY.get(key)
        if c is not None and c.eko_only:
            return connection_catalog.blank(c)
    return value


def values_for(workspace_id) -> Dict[str, Any]:
    if isinstance(workspace_id, str):
        workspace_id = uuid.UUID(workspace_id)
    now = time.monotonic()
    hit = _cache.get(workspace_id)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    with _lock:
        hit = _cache.get(workspace_id)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
        values = _read(workspace_id)
        if values is None:          # could not read: keep what we had
            values = hit[1] if hit else {}
        _cache[workspace_id] = (time.monotonic(), values)
        return values


def forget(workspace_id=None) -> None:
    """Read again next time (after a change in this process)."""
    with _lock:
        if workspace_id is None:
            _cache.clear()
        else:
            if isinstance(workspace_id, str):
                workspace_id = uuid.UUID(workspace_id)
            _cache.pop(workspace_id, None)


def _read(workspace_id) -> Optional[Dict[str, Any]]:
    """The workspace's rows, checked against the list; None on failure."""
    global _last_error_logged
    import psycopg2
    from app.config import get_settings
    s = get_settings().server
    try:
        conn = psycopg2.connect(
            host=s.database_host, port=s.database_port, user=s.database_user,
            password=s.database_password, dbname=s.database_name,
            connect_timeout=3)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM workspace_settings "
                            "WHERE workspace_id = %s", (str(workspace_id),))
                rows = cur.fetchall()
                cur.execute("SELECT key, ciphertext FROM workspace_secrets "
                            "WHERE workspace_id = %s", (str(workspace_id),))
                secrets = cur.fetchall()
        finally:
            conn.close()
    except Exception as e:
        if time.monotonic() - _last_error_logged > 300:
            _last_error_logged = time.monotonic()
            logger.error("workspace_settings: could not read the settings of "
                         "workspace %s (%s: %s) — the last values read are "
                         "kept, else the standard values",
                         workspace_id, type(e).__name__, e)
        return None
    from app.services import connection_catalog, secret_store
    values = {}
    for key, token in secrets:
        if key in connection_catalog.SECRET_KEYS:
            plain = secret_store.unlock_quietly(
                token, f"workspace {workspace_id} {key}")
            if plain is not None:
                values[key] = plain
    for key, value in rows:
        c = connection_catalog.BY_KEY.get(key)
        if c is not None and c.kind != connection_catalog.SECRET:
            try:
                values[key] = connection_catalog.parse(c, value)
            except connection_catalog.ConnectionError_ as e:
                logger.error("workspace_settings: workspace %s: %s", workspace_id, e)
            continue
        if key == "column_map":                 # No. 211: Setup → Columns
            if isinstance(value, dict):
                values[key] = {str(f): str(h) for f, h in value.items()}
            continue
        setting = catalog.BY_KEY.get(key)
        if setting is None:
            continue            # e.g. a setting removed from the list
        try:
            values[key] = catalog.parse(setting, value)
        except SettingError as e:
            logger.error("workspace_settings: workspace %s has a value for %s "
                         "that is no longer allowed (%s) — the standard value "
                         "is used", workspace_id, key, e)
    return values


def standard_value(key: str) -> Any:
    """The server's value: Eko's value today, and every workspace's
    starting point (except NOT_EKO_DEFAULTS outside Eko's workspace)."""
    from app.config import get_settings
    from app.workspace_context import current_workspace_id
    wid = current_workspace_id()
    if key in NOT_EKO_DEFAULTS and wid is not None and wid != EKO_WORKSPACE:
        return NOT_EKO_DEFAULTS[key]
    return getattr(get_settings().server, key)


# ---- who may change what --------------------------------------------------

def is_owner(user: dict) -> bool:
    return (user or {}).get("role") == "super_admin"


def admin_groups(ws) -> List[str]:
    groups = (getattr(ws, "settings", None) or {}).get(ADMIN_GROUPS_KEY) or []
    return [g for g in groups if g in catalog.GROUP_KEYS]


def can_change(user: dict, setting, ws) -> bool:
    if is_owner(user):
        return True
    return ((user or {}).get("role") == "admin"
            and setting.group in admin_groups(ws))


# ---- the screen's view ----------------------------------------------------

async def _workspace(session):
    from sqlalchemy import select
    from app.models.workspace import Workspace
    from app.workspace_context import require_workspace_id
    return (await session.execute(select(Workspace).where(
        Workspace.id == require_workspace_id()))).scalars().first()


async def _rows(session) -> Dict[str, Any]:
    from sqlalchemy import select
    from app.models.workspace_setting import WorkspaceSetting
    return {r.key: r for r in (await session.execute(
        select(WorkspaceSetting))).scalars()}


def _stored(setting, row):
    """A row's value, or None when it is no longer allowed (a range made
    narrower later) — the standard value is then in force, as when reading."""
    if row is None:
        return None
    try:
        return catalog.parse(setting, row.value)
    except SettingError:
        return None


def _neutral(text):
    from app.services import org_identity
    return org_identity.neutral(text)


def _one(setting, row, user, ws) -> dict:
    standard = standard_value(setting.key)
    stored = _stored(setting, row)
    value = stored if stored is not None else standard
    return {
        "key": setting.key, "group": setting.group, "label": setting.label,
        # No. 247: Eko's own examples are not shown to another workspace.
        "help": _neutral(setting.help), "effect": _neutral(setting.effect),
        "kind": setting.kind,
        "unit": setting.unit, "min": setting.min, "max": setting.max,
        "choices": list(setting.choices),
        "value": value, "value_text": catalog.show(setting, value),
        "standard": standard,
        "standard_text": catalog.show(setting, standard),
        "changed": row is not None and value != standard,
        "own": row is not None,
        "changed_by": row.updated_by if row is not None else None,
        "changed_at": row.updated_at.isoformat() if row is not None
        and row.updated_at else None,
        "can_change": can_change(user, setting, ws),
    }


async def describe(session, user) -> dict:
    ws = await _workspace(session)
    rows = await _rows(session)
    handed = admin_groups(ws)
    return {
        "workspace": {"id": str(ws.id), "name": ws.name} if ws else None,
        "groups": [{"key": g.key, "title": g.title, "about": g.about,
                    "admins_may_change": g.key in handed}
                   for g in catalog.GROUPS],
        "settings": [_one(s, rows.get(s.key), user, ws)
                     for s in catalog.SETTINGS],
        "is_owner": is_owner(user),
        "note": _neutral("A setting you have not changed keeps the standard "
                         "value (Eko's value). Changes reach the background "
                         "jobs within half a minute."),
    }


async def one(session, key: str, user) -> dict:
    setting = _setting(key)
    rows = await _rows(session)
    return _one(setting, rows.get(key), user, await _workspace(session))


def _setting(key: str):
    setting = catalog.BY_KEY.get(key)
    if setting is None:
        raise SettingError(f"There is no setting called {key!r}.")
    return setting


# ---- changing -------------------------------------------------------------

def _who(user: dict) -> str:
    return ((user or {}).get("sub") or (user or {}).get("email") or "").lower()


async def _in_force(session, rows) -> Dict[str, Any]:
    out = {}
    for s in catalog.SETTINGS:
        stored = _stored(s, rows.get(s.key))
        out[s.key] = stored if stored is not None else standard_value(s.key)
    return out


async def _record(session, ws, key, old, new, user, via, note=None):
    from app.models.audit_log import AuditLog
    from app.models.workspace_setting import WorkspaceSettingChange
    session.add(WorkspaceSettingChange(
        workspace_id=ws.id, key=key, old_value=old, new_value=new,
        changed_by=_who(user), via=via, note=note))
    session.add(AuditLog(
        workspace_id=ws.id, action="workspace_setting_change",
        resource_type="workspace_setting", resource_id=key, result="success",
        metadata_json={"by": _who(user), "via": via, "before": old,
                       "after": new, "note": note}))


async def set_value(session, key: str, raw: Any, user, via: str = "screen",
                    note: Optional[str] = None) -> dict:
    """Save this workspace's own value. SettingError (plain words) when it
    is not allowed; PermissionError when this person may not change it."""
    from app.models.workspace_setting import WorkspaceSetting
    setting = _setting(key)
    ws = await _workspace(session)
    if not can_change(user, setting, ws):
        raise PermissionError(
            "Only the Super Admin can change this setting"
            + ("" if is_owner(user) else
               " (or an Admin, if the Super Admin hands this group to "
               "Admins)") + ".")
    value = catalog.parse(setting, raw)
    rows = await _rows(session)
    in_force = await _in_force(session, rows)
    catalog.check_together({**in_force, key: value})
    row = rows.get(key)
    old = row.value if row is not None else None
    if row is not None and _stored(setting, row) == value:
        return {**_one(setting, row, user, ws), "unchanged": True}
    if row is None:
        row = WorkspaceSetting(workspace_id=ws.id, key=key, value=value,
                               updated_by=_who(user))
        session.add(row)
    else:
        row.value, row.updated_by = value, _who(user)
    await _record(session, ws, key, old, value, user, via, note)
    await session.commit()
    forget(ws.id)
    logger.info("workspace_settings: %s set %s = %r in %s (%s)", _who(user),
                key, value, ws.slug, via)
    await session.refresh(row)
    return _one(setting, row, user, ws)


async def to_standard(session, key: str, user, via: str = "standard",
                      note: Optional[str] = None) -> dict:
    """Back to the standard (Eko's) value: this workspace's row goes."""
    setting = _setting(key)
    ws = await _workspace(session)
    if not can_change(user, setting, ws):
        raise PermissionError("Only the Super Admin can change this setting.")
    rows = await _rows(session)
    row = rows.get(key)
    if row is None:
        return {**_one(setting, None, user, ws), "unchanged": True}
    in_force = await _in_force(session, rows)
    catalog.check_together({**in_force, key: standard_value(key)})
    old = row.value
    await session.delete(row)
    await _record(session, ws, key, old, None, user, via, note)
    await session.commit()
    forget(ws.id)
    logger.info("workspace_settings: %s put %s back to the standard value in "
                "%s", _who(user), key, ws.slug)
    return _one(setting, None, user, ws)


async def history(session, key: Optional[str] = None,
                  limit: int = 100) -> List[dict]:
    from sqlalchemy import select
    from app.models.workspace_setting import WorkspaceSettingChange
    q = select(WorkspaceSettingChange).order_by(
        WorkspaceSettingChange.id.desc()).limit(max(1, min(limit, 500)))
    if key:
        q = q.where(WorkspaceSettingChange.key == key)
    else:   # only settings; Feature access keeps its own history (No. 206)
        q = q.where(WorkspaceSettingChange.key.in_(
            sorted(catalog.KEYS) + [ADMIN_GROUPS_KEY]))
    out = []
    for c in (await session.execute(q)).scalars():
        setting = catalog.BY_KEY.get(c.key)
        label = setting.label if setting else (
            "Groups Admins may change" if c.key == ADMIN_GROUPS_KEY else c.key)

        def text(v):
            if v is None:
                return "standard value"
            if setting is None:
                return ", ".join(v) if isinstance(v, list) else str(v)
            try:
                return catalog.show(setting, catalog.parse(setting, v))
            except SettingError:
                return str(v)
        out.append({"id": c.id, "key": c.key, "label": label,
                    "before": text(c.old_value), "after": text(c.new_value),
                    "by": c.changed_by, "via": c.via, "note": c.note,
                    "at": c.created_at.isoformat() if c.created_at else None,
                    "can_undo": setting is not None})
    return out


async def undo(session, change_id: int, user) -> dict:
    """Put a setting back to what it was before one change."""
    from sqlalchemy import select
    from app.models.workspace_setting import WorkspaceSettingChange
    change = (await session.execute(select(WorkspaceSettingChange).where(
        WorkspaceSettingChange.id == change_id))).scalars().first()
    if change is None or change.key not in catalog.BY_KEY:
        raise SettingError("That change cannot be undone here.")
    note = f"undo of change {change.id}"
    if change.old_value is None:
        return await to_standard(session, change.key, user, via="undo",
                                 note=note)
    return await set_value(session, change.key, change.old_value, user,
                           via="undo", note=note)


async def set_admin_groups(session, groups: List[str], user) -> List[str]:
    """The Super Admin hands groups of settings to Admins (TK-013)."""
    if not is_owner(user):
        raise PermissionError("Only the Super Admin decides which settings "
                              "Admins may change.")
    clean = []
    for g in groups or []:
        if g not in catalog.GROUP_KEYS:
            raise SettingError(f"There is no settings group {g!r}.")
        if g not in clean:
            clean.append(g)
    ws = await _workspace(session)
    old = admin_groups(ws)
    if sorted(old) == sorted(clean):
        return old
    ws.settings = {**(ws.settings or {}), ADMIN_GROUPS_KEY: clean}
    await _record(session, ws, ADMIN_GROUPS_KEY, old, clean, user, "screen")
    await session.commit()
    logger.info("workspace_settings: %s let Admins change %s in %s",
                _who(user), clean or "nothing", ws.slug)
    return clean
