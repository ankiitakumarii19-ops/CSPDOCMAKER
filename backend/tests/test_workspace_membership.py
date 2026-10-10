"""Workspaces created by Super Admins (tracker No. 48, 11 Oct 2026).

Each test plays someone trying to reach a workspace that is not theirs, or
keep access they have lost. All of them go through `strict_client`, which
grants nobody anything — membership has to be real.
"""

import uuid

import pytest
from sqlalchemy import select, text

from app.models.csp_record import CSPRecord
from app.models.enums import AccountStatus, UserRole
from app.models.user import User
from app.models.workspace import DEFAULT_SLUG, Workspace
from app.models.workspace_member import WorkspaceMember
from app.services import auth_service, jwt_service, otp_service, workspace_service
from app.workspace_context import all_workspaces, workspace
from tests.conftest import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")

EKO_CSP = "EKO-ONLY-1"
PASSWORD = "Password123!"


def _token(email, role, ws=None):
    data = {"sub": email, "role": role, "name": email.split("@")[0]}
    if ws:
        data["ws"] = str(ws)
    return {"Authorization": f"Bearer {jwt_service.create_access_token(data)}"}


@pytest.fixture
async def eko_csp(db):
    db.add(CSPRecord(csp_id=EKO_CSP, name="Eko Agent", origin="new"))
    await db.commit()


@pytest.fixture
async def other_ws(db):
    """A second workspace, created exactly as sign-up creates one."""
    with all_workspaces():
        await db.execute(text(
            "DELETE FROM workspaces WHERE name LIKE 'Test Workspace%'"))
        await db.commit()
    ws = await workspace_service.create_workspace(
        db, f"Test Workspace {uuid.uuid4().hex[:6]}",
        "outsider@eko.co.in", "Outsider")
    await db.commit()
    yield ws
    with all_workspaces():
        await db.execute(text("DELETE FROM workspaces WHERE id = :w")
                         .bindparams(w=ws.id))
        await db.commit()


async def _member(db, email, role, ws_id=DEFAULT_WORKSPACE_ID, active=True,
                  added_by=None):
    with all_workspaces():
        db.add(WorkspaceMember(workspace_id=ws_id, email=email, role=role,
                               active=active, added_by_email=added_by))
        await db.commit()


# ---- creating a workspace -------------------------------------------------

async def test_signing_up_as_super_admin_creates_a_named_workspace(db):
    ok, message, user = await auth_service.signup_user(
        db=db, email="founder@eko.co.in", name="Founder", password=PASSWORD,
        requested_role="super_admin", workspace_name="  Patna   Pilot  ")
    await db.commit()
    assert ok, message
    with all_workspaces():
        ws = (await db.execute(select(Workspace).where(
            Workspace.id == user.workspace_id))).scalars().one()
        assert ws.name == "Patna Pilot"
        assert ws.slug != DEFAULT_SLUG
        members = (await db.execute(select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id))).scalars().all()
        assert [(m.email, m.role) for m in members] == [
            ("founder@eko.co.in", UserRole.SUPER_ADMIN)]
        await db.execute(text("DELETE FROM workspaces WHERE id = :w")
                         .bindparams(w=ws.id))
        await db.commit()


async def test_a_workspace_name_cannot_be_used_twice(db, other_ws):
    ok, message, _ = await auth_service.signup_user(
        db=db, email="copycat@eko.co.in", name="Copy", password=PASSWORD,
        requested_role="super_admin", workspace_name=other_ws.name.upper())
    assert not ok and "already exists" in message


async def test_a_workspace_cannot_be_created_from_another_domain(db):
    ok, _, _ = await auth_service.signup_user(
        db=db, email="stranger@gmail.com", name="Stranger", password=PASSWORD,
        requested_role="super_admin", workspace_name="Mine")
    assert not ok


async def test_the_present_workspace_is_called_eko_sbi_kiosk_csp(db):
    with all_workspaces():
        ws = (await db.execute(select(Workspace).where(
            Workspace.slug == DEFAULT_SLUG))).scalars().one()
    assert ws.name == "Eko SBI Kiosk CSP"


# ---- nobody sees another workspace ----------------------------------------

async def test_a_new_super_admin_cannot_see_eko_records(
        strict_client, db, eko_csp, other_ws):
    headers = _token("outsider@eko.co.in", "super_admin", other_ws.id)
    r = await strict_client.get(f"/api/csps/{EKO_CSP}", headers=headers)
    assert r.status_code == 404


async def test_eko_still_sees_its_own_records(strict_client, db, eko_csp):
    await _member(db, "boss@eko.co.in", UserRole.SUPER_ADMIN)
    r = await strict_client.get(
        f"/api/csps/{EKO_CSP}",
        headers=_token("boss@eko.co.in", "super_admin", DEFAULT_WORKSPACE_ID))
    assert r.status_code == 200


async def test_naming_someone_elses_workspace_in_a_token_is_refused(
        strict_client, db, eko_csp, other_ws):
    # The outsider forges a token naming Eko's workspace.
    headers = _token("outsider@eko.co.in", "super_admin", DEFAULT_WORKSPACE_ID)
    r = await strict_client.get(f"/api/csps/{EKO_CSP}", headers=headers)
    assert r.status_code == 403


async def test_a_signed_in_stranger_is_refused_not_left_unfiltered(
        strict_client, db, eko_csp):
    # No membership anywhere. Before 11 Oct this request ran with no
    # workspace filter at all — and so could read every workspace.
    r = await strict_client.get(f"/api/csps/{EKO_CSP}",
                                headers=_token("nobody@eko.co.in", "rm"))
    assert r.status_code == 403


async def test_removed_access_stops_at_the_next_request(
        strict_client, db, eko_csp):
    await _member(db, "leaver@eko.co.in", UserRole.SUPER_ADMIN)
    headers = _token("leaver@eko.co.in", "super_admin", DEFAULT_WORKSPACE_ID)
    assert (await strict_client.get(f"/api/csps/{EKO_CSP}",
                                    headers=headers)).status_code == 200
    with all_workspaces():
        await db.execute(text("UPDATE workspace_members SET active = false "
                              "WHERE email = 'leaver@eko.co.in'"))
        await db.commit()
    assert (await strict_client.get(f"/api/csps/{EKO_CSP}",
                                    headers=headers)).status_code == 403


async def test_a_changed_role_forces_a_new_login(strict_client, db, eko_csp):
    await _member(db, "demoted@eko.co.in", UserRole.RM)
    headers = _token("demoted@eko.co.in", "super_admin", DEFAULT_WORKSPACE_ID)
    r = await strict_client.get(f"/api/csps/{EKO_CSP}", headers=headers)
    assert r.status_code == 401


# ---- choosing a workspace at login ----------------------------------------

@pytest.fixture
def captured_codes(monkeypatch):
    try:
        redis = otp_service._get_redis()
    except RuntimeError:
        pytest.skip("Redis not reachable")
    for pattern in ("otp:*", "otp_rate:*", "otp_attempts:*"):
        keys = redis.keys(pattern)
        if keys:
            redis.delete(*keys)
    from app.routers import auth_router
    sent = []
    monkeypatch.setattr(
        auth_router.email_service, "send_otp_email",
        lambda to_email, otp_code, user_name=None, subject=None:
            (sent.append(otp_code), True)[1])
    return sent


async def _login(client, email, codes):
    await client.post("/api/auth/login",
                      json={"email": email, "password": PASSWORD})
    return (await client.post("/api/auth/verify-otp",
                              json={"email": email, "otp": codes[-1]})).json()


async def test_someone_in_two_workspaces_is_asked_which(
        strict_client, db, other_ws, captured_codes):
    email = "twohats@eko.co.in"
    db.add(User(email=email, name="Two Hats", mobile="", role=UserRole.RM,
                account_status=AccountStatus.ACTIVE,
                password_hash=auth_service.hash_password(PASSWORD)))
    await db.commit()
    await _member(db, email, UserRole.RM)
    await _member(db, email, UserRole.ADMIN, ws_id=other_ws.id,
                  added_by="outsider@eko.co.in")

    body = await _login(strict_client, email, captured_codes)
    assert body["choose_workspace"] is True
    assert not body.get("access_token"), "no workspace is assumed"
    names = {w["name"]: w["role"] for w in body["workspaces"]}
    assert names == {"Eko SBI Kiosk CSP": "rm", other_ws.name: "admin"}

    chosen = (await strict_client.post("/api/auth/select-workspace", json={
        "selection_token": body["selection_token"],
        "workspace_id": str(other_ws.id)})).json()
    assert chosen["role"] == "admin"
    assert chosen["workspace_name"] == other_ws.name
    claims = jwt_service.verify_access_token(chosen["access_token"])
    assert claims["ws"] == str(other_ws.id) and claims["role"] == "admin"


async def test_the_chooser_cannot_be_used_to_enter_a_foreign_workspace(
        strict_client, db, other_ws):
    token = jwt_service.create_selection_token("someone@eko.co.in")
    r = await strict_client.post("/api/auth/select-workspace", json={
        "selection_token": token, "workspace_id": str(other_ws.id)})
    assert r.status_code == 403


async def test_a_real_access_token_is_not_a_selection_token(
        strict_client, db, other_ws):
    access = jwt_service.create_access_token(
        {"sub": "outsider@eko.co.in", "role": "super_admin"})
    r = await strict_client.post("/api/auth/select-workspace", json={
        "selection_token": access, "workspace_id": str(other_ws.id)})
    assert r.status_code == 401


async def test_the_settings_list_does_not_demote_a_workspace_creator(
        strict_client, db, other_ws, captured_codes, monkeypatch):
    db.add(User(email="outsider@eko.co.in", name="Outsider", mobile="",
                role=UserRole.SUPER_ADMIN, workspace_id=other_ws.id,
                account_status=AccountStatus.ACTIVE,
                password_hash=auth_service.hash_password(PASSWORD)))
    await db.commit()
    body = await _login(strict_client, "outsider@eko.co.in", captured_codes)
    assert body["role"] == "super_admin"
    assert body["workspace_id"] == str(other_ws.id)


# ---- adding and removing people -------------------------------------------

async def test_a_super_admin_adds_people_to_their_own_workspace_only(
        strict_client, db, other_ws):
    headers = _token("outsider@eko.co.in", "super_admin", other_ws.id)
    r = await strict_client.post("/api/admin/access/grant", headers=headers,
                                 json={"email": "helper@eko.co.in",
                                       "name": "Helper", "role": "rm"})
    assert r.status_code == 201, r.text
    assert r.json()["added_by"] == "outsider@eko.co.in"
    assert "sheet" not in r.json(), "only Eko writes to the sheet"

    with all_workspaces():
        rows = (await db.execute(select(WorkspaceMember).where(
            WorkspaceMember.email == "helper@eko.co.in"))).scalars().all()
    assert [(r.workspace_id, r.added_by_email) for r in rows] == [
        (other_ws.id, "outsider@eko.co.in")]

    listing = (await strict_client.get("/api/admin/access",
                                       headers=headers)).json()
    assert listing["workspace"]["name"] == other_ws.name
    assert listing["by_super_admin"]["outsider@eko.co.in"] == [
        "helper@eko.co.in"]


async def test_the_last_super_admin_cannot_be_removed(
        strict_client, db, other_ws):
    await _member(db, "second@eko.co.in", UserRole.SUPER_ADMIN,
                  ws_id=other_ws.id, added_by="outsider@eko.co.in")
    headers = _token("second@eko.co.in", "super_admin", other_ws.id)
    ok = await strict_client.post("/api/admin/access/revoke", headers=headers,
                                  json={"email": "outsider@eko.co.in"})
    assert ok.status_code == 200
    # "second" is now the only one left, and cannot remove themselves.
    me = await strict_client.post("/api/admin/access/revoke", headers=headers,
                                  json={"email": "second@eko.co.in"})
    assert me.status_code == 409


async def test_an_rm_cannot_add_anyone(strict_client, db, other_ws):
    await _member(db, "plainrm@eko.co.in", UserRole.RM, ws_id=other_ws.id)
    r = await strict_client.post(
        "/api/admin/access/grant",
        headers=_token("plainrm@eko.co.in", "rm", other_ws.id),
        json={"email": "x@eko.co.in", "name": "X", "role": "super_admin"})
    assert r.status_code == 403


async def test_someone_added_in_the_app_can_sign_up(db, other_ws):
    await _member(db, "invited@eko.co.in", UserRole.ADMIN, ws_id=other_ws.id,
                  added_by="outsider@eko.co.in")
    ok, message, user = await auth_service.signup_user(
        db=db, email="invited@eko.co.in", name="Invited", password=PASSWORD,
        requested_role="admin")
    assert ok, message
    assert user.workspace_id == other_ws.id


# ---- the background jobs ---------------------------------------------------

async def test_sheet_jobs_run_only_for_eko(db, other_ws, monkeypatch):
    from app.workers import workspace_runner

    seen = []

    @workspace_runner.for_configured_workspace
    def job():
        from app.workspace_context import current_workspace_id
        seen.append(current_workspace_id())

    job()
    assert seen == [DEFAULT_WORKSPACE_ID]


def test_the_two_sheet_reading_jobs_use_the_eko_only_runner():
    import inspect
    from app.workers import auth_sync_worker, csp_sync_worker
    for module in (csp_sync_worker, auth_sync_worker):
        assert "@for_configured_workspace" in inspect.getsource(module)


# ---- the Access Control screen's contract ---------------------------------
#
# On 11 Oct the listing's shape was changed without the screen, and the
# screen crashed reading `super_admins.length`. These pin the keys that
# AccessListing in frontend/app/lib/api.ts relies on.

SCREEN_KEYS = {"people", "total", "super_admins", "source",
               "sync_interval_minutes"}
PERSON_KEYS = {"email", "name", "mobile", "role", "active", "registered",
               "last_login", "synchronized_at"}


async def test_the_access_listing_keeps_the_shape_the_screen_reads(
        strict_client, db, other_ws):
    await _member(db, "helper2@eko.co.in", UserRole.RM, ws_id=other_ws.id,
                  added_by="outsider@eko.co.in")
    body = (await strict_client.get(
        "/api/admin/access",
        headers=_token("outsider@eko.co.in", "super_admin", other_ws.id),
    )).json()
    assert SCREEN_KEYS <= body.keys()
    assert body["super_admins"] == ["outsider@eko.co.in"]
    assert isinstance(body["sync_interval_minutes"], int)
    assert body["people"], "the RM should be listed"
    for person in body["people"]:
        assert PERSON_KEYS <= person.keys()
        # The screen's table is RMs and Admins; Super Admins go in the box.
        assert person["role"] in ("rm", "admin")
