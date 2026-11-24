"""
CSP DocMaker — who may use which feature (PROJECT-REGISTER No. 206, Stage 2:
TK-016 - TK-019, ZU-02)

The decision, for a signed-in person in a workspace:

  * a Super Admin: exactly what they have today (everything, except making
    documents, which is the RM's screen) — never changed by anything here;
  * a locked feature (feature_catalog): exactly today's access;
  * otherwise the first answer found in:
        1. this person               feature_access subject "person:<email>"
        2. their own role, if any    "role:<key>"   (workspace_members.access_role)
           else their built-in role  "role:rm" / "role:admin"
        3. today's access            feature_catalog.Feature.default
    and a feature given to someone whose kind (RM / Admin) it may not be
    given to is refused even if a row says so.

Which CSPs: an RM acts on their own CSPs and unowned ones (today); a role
set to "all" acts on every CSP (csp_access asks record_scope()). Admins
always see every CSP.

Enforced on the server, in dependencies.require_role / require_any_role, on
every route a feature lists; the screens only follow (GET /api/me/access).

Read in any process from the database, kept CACHE_SECONDS per workspace and
forgotten at once after a change made in this process. If it cannot be
read, the last values read are kept (else today's access), logged as an
error.
"""

import logging
import re
import threading
import time
import uuid
from typing import Dict, List, Optional

from app.services import feature_catalog as catalog

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30
RM, ADMIN, SUPER = "rm", "admin", "super_admin"
BUILT_IN = {RM: "RM", ADMIN: "Admin"}
SCOPES = ("own", "all")
# Screens that live on the Admin pages: an RM given one of these may open
# the Admin pages (only these screens show).
ADMIN_AREA = ("dashboard", "dashboards", "whatsapp", "emails", "replies",
              "data_quality", "templates", "messaging", "knowledge",
              "settings", "rules_view", "reply_mode", "agents")


class AccessError(ValueError):
    """A change that cannot be made; the text says why."""


_cache: Dict[uuid.UUID, tuple] = {}
_lock = threading.Lock()
_last_error = 0.0
_EMPTY = {"grants": {}, "roles": {}, "members": {}}


# ---- reading --------------------------------------------------------------

def _data(workspace_id) -> dict:
    if workspace_id is None:
        return _EMPTY
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
        data = _read(workspace_id)
        if data is None:
            data = hit[1] if hit else _EMPTY
        _cache[workspace_id] = (time.monotonic(), data)
        return data


def forget(workspace_id=None) -> None:
    with _lock:
        if workspace_id is None:
            _cache.clear()
        else:
            if isinstance(workspace_id, str):
                workspace_id = uuid.UUID(workspace_id)
            _cache.pop(workspace_id, None)


def _read(workspace_id) -> Optional[dict]:
    global _last_error
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
                w = str(workspace_id)
                cur.execute("SELECT feature, subject, allowed FROM "
                            "feature_access WHERE workspace_id = %s", (w,))
                grants = {(f, sub): bool(a) for f, sub, a in cur.fetchall()}
                cur.execute("SELECT key, name, base_role, record_scope FROM "
                            "access_roles WHERE workspace_id = %s", (w,))
                roles = {k: {"name": n, "base": b, "scope": sc}
                         for k, n, b, sc in cur.fetchall()}
                cur.execute("SELECT lower(email), access_role FROM "
                            "workspace_members WHERE workspace_id = %s AND "
                            "access_role IS NOT NULL AND active", (w,))
                members = dict(cur.fetchall())
        finally:
            conn.close()
    except Exception as e:
        if time.monotonic() - _last_error > 300:
            _last_error = time.monotonic()
            logger.error("feature_access: could not read who has which "
                         "feature in workspace %s (%s: %s) — the last values "
                         "read are kept, else today's access",
                         workspace_id, type(e).__name__, e)
        return None
    return {"grants": grants, "roles": roles, "members": members}


def _workspace_now():
    from app.workspace_context import current_workspace_id
    return current_workspace_id()


def _email(user: dict) -> str:
    return ((user or {}).get("sub") or (user or {}).get("email")
            or "").strip().lower()


def _base(user: dict) -> str:
    return ((user or {}).get("role") or "").lower()


def own_role(user: dict, data: Optional[dict] = None) -> Optional[str]:
    """The key of this person's own role, if they have one that exists and
    is built on their kind (RM / Admin)."""
    data = data or _data(_workspace_now())
    key = data["members"].get(_email(user))
    role = data["roles"].get(key) if key else None
    if role is None or key in BUILT_IN or role["base"] != _base(user):
        return None
    return key


def allowed(feature, user: dict, data: Optional[dict] = None) -> bool:
    """Whether this person may use this feature now."""
    f = catalog.BY_KEY[feature] if isinstance(feature, str) else feature
    base = _base(user)
    if base == SUPER:
        return f.owner
    if base not in (RM, ADMIN):
        return False
    if f.locked:
        return base in f.default
    data = data or _data(_workspace_now())
    grants = data["grants"]
    role = own_role(user, data) or base
    value = None
    for subject in (f"person:{_email(user)}", f"role:{role}"):
        if (f.key, subject) in grants:
            value = grants[(f.key, subject)]
            break
    if value is None:
        value = base in f.default
    if value and base not in f.default and base not in f.can_give_to:
        return False
    return value


def record_scope(user: dict) -> str:
    """Which CSPs this person may act on: "all" or "own" (their own and
    unowned ones)."""
    base = _base(user)
    if base in (ADMIN, SUPER):
        return "all"
    data = _data(_workspace_now())
    key = own_role(user, data) or base
    role = data["roles"].get(key)
    return role["scope"] if role and role.get("scope") in SCOPES else "own"


def check_route(method: str, path: str, user: dict) -> Optional[bool]:
    """For the role checks on every route: None = not a feature (decide as
    before); True / False = this person may / may not."""
    base = _base(user)
    if base not in (RM, ADMIN) or _workspace_now() is None:
        return None
    f = catalog.feature_for(method, path)
    if f is None:
        return None
    return allowed(f, user)


def mine(user: dict) -> dict:
    """GET /api/me/access: what this person may use, for the screens."""
    data = _data(_workspace_now())
    keys = [f.key for f in catalog.FEATURES if allowed(f, user, data)]
    base = _base(user)
    key = own_role(user, data) if base in (RM, ADMIN) else None
    name = (data["roles"][key]["name"] if key else
            {"super_admin": "Super Admin", **BUILT_IN}.get(base, base))
    from app.config import get_settings
    s = get_settings()
    return {"role": base, "own_role": key, "role_name": name,
            # No. 214: the workspace's own name and colour.
            "look": {"name": s.brand_name, "color": s.brand_color,
                     "theme": s.ui_theme, "style": s.ui_style},
            "features": keys, "record_scope": record_scope(user),
            "admin_area": base in (ADMIN, SUPER)
            or any(k in ADMIN_AREA for k in keys)}


# ---- the Feature access screen ------------------------------------------------

def _who(user: dict) -> str:
    return _email(user)


async def _workspace(session):
    from app.services.workspace_settings import _workspace as ws
    return await ws(session)


async def _rows(session):
    from sqlalchemy import select
    from app.models.feature_access import AccessRole, FeatureAccess
    from app.models.workspace_member import WorkspaceMember
    grants = {(r.feature, r.subject): r for r in (await session.execute(
        select(FeatureAccess))).scalars()}
    roles = {r.key: r for r in (await session.execute(
        select(AccessRole))).scalars()}
    members = list((await session.execute(select(WorkspaceMember).where(
        WorkspaceMember.active.is_(True)).order_by(
        WorkspaceMember.email))).scalars())
    return grants, roles, members


def _snapshot(grants, roles, members) -> dict:
    return {"grants": {k: r.allowed for k, r in grants.items()},
            "roles": {k: {"name": r.name, "base": r.base_role,
                          "scope": r.record_scope} for k, r in roles.items()},
            "members": {m.email.lower(): m.access_role for m in members
                        if m.access_role}}


def _role_list(roles, members) -> List[dict]:
    out = []
    for key, name in BUILT_IN.items():
        row = roles.get(key)
        out.append({"key": key, "name": name, "base_role": key,
                    "record_scope": "all" if key == ADMIN else (
                        row.record_scope if row else "own"),
                    "built_in": True,
                    "members": sum(1 for m in members if m.role.value == key
                                   and not (m.access_role and m.access_role
                                            in roles))})
    for key, r in sorted(roles.items(), key=lambda kv: kv[1].name.lower()):
        if key in BUILT_IN:
            continue
        out.append({"key": key, "name": r.name, "base_role": r.base_role,
                    "record_scope": r.record_scope if r.base_role == RM
                    else "all", "built_in": False,
                    "members": sum(1 for m in members
                                   if m.access_role == key)})
    return out


async def describe(session) -> dict:
    grants, roles, members = await _rows(session)
    data = _snapshot(grants, roles, members)
    role_list = _role_list(roles, members)
    grid = {}
    for r in role_list:
        probe = {"role": r["base_role"], "sub": f"__role__{r['key']}"}
        data_r = {**data, "members": {**data["members"],
                                      probe["sub"]: r["key"]}}
        grid[r["key"]] = {
            f.key: {"allowed": allowed(f, probe, data_r),
                    "set": (f.key, f"role:{r['key']}") in grants,
                    "can_change": _changeable(f, r["base_role"])}
            for f in catalog.FEATURES}
    people = []
    for m in members:
        if m.role.value not in (RM, ADMIN):
            continue
        mine_ = {f: g.allowed for (f, sub), g in grants.items()
                 if sub == f"person:{m.email.lower()}"}
        user = {"role": m.role.value, "sub": m.email}
        people.append({
            "email": m.email, "name": m.name, "role": m.role.value,
            "own_role": m.access_role if m.access_role in roles else None,
            "overrides": mine_,
            "features": [f.key for f in catalog.FEATURES
                         if allowed(f, user, data)]})
    return {
        "groups": [{"key": k, "title": t} for k, t in catalog.GROUPS],
        "features": [{"key": f.key, "group": f.group, "title": f.title,
                      "about": f.about, "default": list(f.default),
                      "can_give_to": list(f.can_give_to), "locked": f.locked,
                      "all_csps": f.all_csps, "owner": f.owner}
                     for f in catalog.FEATURES],
        "roles": role_list, "grid": grid, "people": people,
        "note": ("The Super Admin always keeps every feature. A feature not "
                 "changed here is exactly as before. The server refuses a "
                 "feature that is switched off, not only the screen."),
    }


def _changeable(f, base: str) -> bool:
    return not f.locked and (base in f.default or base in f.can_give_to)


def _feature(key: str):
    f = catalog.BY_KEY.get(key)
    if f is None:
        raise AccessError(f"There is no feature called {key!r}.")
    if f.locked:
        raise AccessError(f"“{f.title}” stays with the Super Admin; it "
                          "cannot be given or taken here.")
    return f


def _kind(base: str) -> str:
    return "RMs" if base == RM else "Admins"


def _check_give(f, base: str, value: Optional[bool]) -> None:
    if value and base not in f.default and base not in f.can_give_to:
        raise AccessError(f"“{f.title}” cannot be given to {_kind(base)}.")


async def _record(session, ws, key, old, new, user, via, note=None):
    from app.services.workspace_settings import _record as record
    await record(session, ws, key, old, new, user, via, note)


async def _done(session, ws):
    await session.commit()
    forget(ws.id)


async def set_for_role(session, role_key: str, feature: str,
                       value: Optional[bool], user, via: str = "screen"):
    """Give (True), take (False) or put back to today's access (None)."""
    from app.models.feature_access import FeatureAccess
    f = _feature(feature)
    grants, roles, members = await _rows(session)
    if role_key in BUILT_IN:
        base = role_key
    elif role_key in roles:
        base = roles[role_key].base_role
    else:
        raise AccessError(f"There is no role {role_key!r}.")
    _check_give(f, base, value)
    ws = await _workspace(session)
    subject = f"role:{role_key}"
    row = grants.get((f.key, subject))
    old = row.allowed if row is not None else None
    if old == value:
        return
    if value is None:
        await session.delete(row)
    elif row is None:
        session.add(FeatureAccess(workspace_id=ws.id, feature=f.key,
                                  subject=subject, allowed=value,
                                  updated_by=_who(user)))
    else:
        row.allowed, row.updated_by = value, _who(user)
    await _record(session, ws, f"access:{f.key}:{subject}", old, value, user,
                  via)
    await _done(session, ws)
    logger.info("feature_access: %s set %s for %s = %s (%s)", _who(user),
                f.key, subject, value, via)


async def set_for_person(session, email: str, feature: str,
                         value: Optional[bool], user, via: str = "screen"):
    from app.models.feature_access import FeatureAccess
    f = _feature(feature)
    email = (email or "").strip().lower()
    grants, roles, members = await _rows(session)
    member = next((m for m in members if m.email.lower() == email), None)
    if member is None:
        raise AccessError(f"{email} is not a member of this workspace.")
    base = member.role.value
    if base not in (RM, ADMIN):
        raise AccessError("A Super Admin always keeps every feature.")
    _check_give(f, base, value)
    ws = await _workspace(session)
    subject = f"person:{email}"
    row = grants.get((f.key, subject))
    old = row.allowed if row is not None else None
    if old == value:
        return
    if value is None:
        await session.delete(row)
    elif row is None:
        session.add(FeatureAccess(workspace_id=ws.id, feature=f.key,
                                  subject=subject, allowed=value,
                                  updated_by=_who(user)))
    else:
        row.allowed, row.updated_by = value, _who(user)
    await _record(session, ws, f"access:{f.key}:{subject}", old, value, user,
                  via)
    await _done(session, ws)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:50]
    return s or "role"


async def create_role(session, name: str, copy_from: str, user) -> dict:
    """A workspace's own role, starting as a copy of another (its kind, its
    features and its CSPs)."""
    from app.models.feature_access import AccessRole, FeatureAccess
    name = " ".join((name or "").split())
    if not 2 <= len(name) <= 60:
        raise AccessError("Give the role a name of 2-60 characters.")
    grants, roles, members = await _rows(session)
    if name.lower() in {v.lower() for v in BUILT_IN.values()} | {
            r.name.lower() for k, r in roles.items() if k not in BUILT_IN}:
        raise AccessError(f"There is already a role called {name!r}.")
    if copy_from in BUILT_IN:
        base = copy_from
        scope = (roles[copy_from].record_scope if copy_from in roles
                 else ("all" if copy_from == ADMIN else "own"))
    elif copy_from in roles:
        base, scope = roles[copy_from].base_role, roles[copy_from].record_scope
    else:
        raise AccessError("Choose the role to start from.")
    key, n = _slug(name), 2
    while key in roles or key in BUILT_IN:
        key, n = f"{_slug(name)}-{n}", n + 1
    ws = await _workspace(session)
    session.add(AccessRole(workspace_id=ws.id, key=key, name=name,
                           base_role=base, record_scope=scope,
                           created_by=_who(user)))
    for (feature, subject), g in grants.items():
        if subject == f"role:{copy_from}":
            session.add(FeatureAccess(workspace_id=ws.id, feature=feature,
                                      subject=f"role:{key}",
                                      allowed=g.allowed,
                                      updated_by=_who(user)))
    await _record(session, ws, f"role:{key}", None,
                  {"name": name, "base_role": base, "record_scope": scope,
                   "copied_from": copy_from}, user, "screen")
    await _done(session, ws)
    return {"key": key, "name": name, "base_role": base,
            "record_scope": scope}


async def change_role(session, key: str, user, name: Optional[str] = None,
                      record_scope: Optional[str] = None) -> None:
    from app.models.feature_access import AccessRole
    grants, roles, members = await _rows(session)
    ws = await _workspace(session)
    if key in BUILT_IN:
        if name is not None:
            raise AccessError("The built-in roles keep their names (renaming "
                              "words comes in a later stage).")
        if key == ADMIN and record_scope not in (None, "all"):
            raise AccessError("Admins always see every CSP.")
    elif key not in roles:
        raise AccessError(f"There is no role {key!r}.")
    row = roles.get(key)
    base = key if key in BUILT_IN else row.base_role
    if record_scope is not None:
        if record_scope not in SCOPES:
            raise AccessError("Choose own or all.")
        if base == ADMIN and record_scope != "all":
            raise AccessError("Roles built on Admin always see every CSP.")
    old = ({"name": row.name, "record_scope": row.record_scope} if row
           else {"name": BUILT_IN[key], "record_scope": "own"})
    new = dict(old)
    if name is not None:
        name = " ".join(name.split())
        if not 2 <= len(name) <= 60:
            raise AccessError("Give the role a name of 2-60 characters.")
        if name.lower() != old["name"].lower() and name.lower() in {
                r.name.lower() for r in roles.values()} | {
                v.lower() for v in BUILT_IN.values()}:
            raise AccessError(f"There is already a role called {name!r}.")
        new["name"] = name
    if record_scope is not None:
        new["record_scope"] = record_scope
    if new == old:
        return
    if row is None:
        session.add(AccessRole(workspace_id=ws.id, key=key,
                               name=BUILT_IN[key], base_role=key,
                               record_scope=new["record_scope"],
                               created_by=_who(user)))
    else:
        row.name, row.record_scope = new["name"], new["record_scope"]
    await _record(session, ws, f"role:{key}", old, new, user, "screen")
    await _done(session, ws)


async def delete_role(session, key: str, user) -> None:
    from sqlalchemy import delete
    from app.models.feature_access import FeatureAccess
    grants, roles, members = await _rows(session)
    if key in BUILT_IN or key not in roles:
        raise AccessError("Only a role you made can be removed.")
    using = [m.email for m in members if m.access_role == key]
    if using:
        raise AccessError(f"{len(using)} member(s) have this role "
                          f"({', '.join(using[:3])}); give them another "
                          "role first.")
    ws = await _workspace(session)
    old = {"name": roles[key].name, "base_role": roles[key].base_role,
           "record_scope": roles[key].record_scope}
    await session.execute(delete(FeatureAccess).where(
        FeatureAccess.subject == f"role:{key}",
        FeatureAccess.workspace_id == ws.id))
    await session.delete(roles[key])
    await _record(session, ws, f"role:{key}", old, None, user, "screen")
    await _done(session, ws)


async def set_member_role(session, email: str, key: Optional[str],
                          user) -> None:
    """Give a member one of the workspace's own roles (None = back to the
    built-in RM / Admin role)."""
    grants, roles, members = await _rows(session)
    email = (email or "").strip().lower()
    member = next((m for m in members if m.email.lower() == email), None)
    if member is None:
        raise AccessError(f"{email} is not a member of this workspace.")
    if key in (None, "", member.role.value):
        key = None
    elif key not in roles or key in BUILT_IN:
        raise AccessError(f"There is no role {key!r}.")
    elif roles[key].base_role != member.role.value:
        raise AccessError(f"“{roles[key].name}” is built on "
                          f"{BUILT_IN[roles[key].base_role]}; {email} is "
                          f"{'an' if member.role.value == ADMIN else 'a'} "
                          f"{BUILT_IN.get(member.role.value, 'Super Admin')}.")
    if member.access_role == key:
        return
    ws = await _workspace(session)
    old = member.access_role
    member.access_role = key
    await _record(session, ws, f"member_role:{email}", old, key, user,
                  "screen")
    await _done(session, ws)


async def history(session, limit: int = 100) -> List[dict]:
    from sqlalchemy import or_, select
    from app.models.workspace_setting import WorkspaceSettingChange as C
    rows = (await session.execute(select(C).where(or_(
        C.key.like("access:%"), C.key.like("role:%"),
        C.key.like("member_role:%"))).order_by(C.id.desc()).limit(
        max(1, min(limit, 500))))).scalars()

    def show(v):
        if v is None:
            return "as before (today's access)"
        if v is True:
            return "given"
        if v is False:
            return "taken away"
        if isinstance(v, dict):
            return ", ".join(f"{k.replace('_', ' ')}: {x}" for k, x in v.items())
        return str(v)
    out = []
    for c in rows:
        parts = c.key.split(":", 2)
        if parts[0] == "access":
            f = catalog.BY_KEY.get(parts[1])
            what = f"{f.title if f else parts[1]} — {parts[2].replace(':', ' ')}"
        elif parts[0] == "role":
            what = f"Role {parts[1]}"
        else:
            what = f"Role of {parts[1]}"
        out.append({"id": c.id, "what": what, "before": show(c.old_value),
                    "after": show(c.new_value), "by": c.changed_by,
                    "via": c.via,
                    "at": c.created_at.isoformat() if c.created_at else None})
    return out
