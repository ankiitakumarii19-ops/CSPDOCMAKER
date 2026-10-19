"""Each workspace's own rules (tracker No. 120).

Every test runs in a fresh workspace created as sign-up creates one, so the
Eko workspace's rules are never touched. Sign-ins go through strict_client:
membership — and the workspace's domain rule — has to be real.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.models.audit_log import AuditLog
from app.models.enums import UserRole
from app.models.messaging import MessageTemplate
from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember
from app.services import jwt_service, workspace_rules, workspace_service
from app.workspace_context import all_workspaces, workspace

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER = "rules.owner@eko.co.in"


@pytest.fixture
async def ws(migrated_db):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        created = await workspace_service.create_workspace(
            s, f"Rules Test {uuid.uuid4().hex[:6]}", OWNER, "Rules Owner")
        await s.commit()
        yield created
        with all_workspaces():
            await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                            .bindparams(w=created.id))
            await s.commit()


async def _member(ws, email, role):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with all_workspaces():
            s.add(WorkspaceMember(workspace_id=ws.id, email=email, role=role,
                                  active=True))
            await s.commit()


async def _settings(ws) -> dict:
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with all_workspaces():
            return (await s.execute(select(Workspace.settings).where(
                Workspace.id == ws.id))).scalar()


def _h(ws, email, role):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": email, "email": email, "role": role,
        "name": email.split("@")[0], "ws": str(ws.id)})}


RULES = {"allowed_email_domains": ["eko.co.in", "@ABC.com "],
         "session_hours": 12, "members_added_by": "owner_and_admins",
         "message_signoff": "Team Patna Pilot"}


# ---- the rules themselves ---------------------------------------------------------

async def test_a_new_workspace_starts_with_its_owners_domain(ws):
    assert ws.settings == {"allowed_email_domains": ["eko.co.in"]}
    assert workspace_rules.session_hours(ws) == 24
    assert workspace_rules.members_added_by(ws) == "owner"


async def test_the_owner_sets_the_rules_and_it_is_audited(strict_client, ws):
    r = await strict_client.put("/api/admin/workspace-rules", json=RULES,
                                headers=_h(ws, OWNER, "super_admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed_email_domains"] == ["eko.co.in", "abc.com"]
    assert body["session_hours"] == 12
    assert body["members_added_by"] == "owner_and_admins"
    saved = await _settings(ws)
    assert saved["message_signoff"] == "Team Patna Pilot"
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with all_workspaces():
            audit = (await s.execute(select(AuditLog).where(
                AuditLog.workspace_id == ws.id,
                AuditLog.action == "workspace_rules_change"))).scalars().one()
    assert audit.metadata_json["by"] == OWNER
    assert audit.metadata_json["before"]["session_hours"] == 24


@pytest.mark.parametrize("change,why", [
    ({"allowed_email_domains": ["abc.com"]}, "lock out"),
    ({"allowed_email_domains": ["not a domain"]}, "not an email domain"),
    ({"session_hours": 0}, "between 1 and 720"),
    ({"session_hours": 1000}, "between 1 and 720"),
    ({"members_added_by": "everyone"}, "who can add members"),
])
async def test_rules_that_cannot_be_saved(strict_client, ws, change, why):
    r = await strict_client.put("/api/admin/workspace-rules",
                                json={**RULES, **change},
                                headers=_h(ws, OWNER, "super_admin"))
    assert r.status_code == 400 and why in r.text, r.text


async def test_only_the_owner_changes_rules_admins_may_read(strict_client, ws):
    await _member(ws, "rules.admin@eko.co.in", UserRole.ADMIN)
    await _member(ws, "rules.rm@eko.co.in", UserRole.RM)
    admin = _h(ws, "rules.admin@eko.co.in", "admin")
    assert (await strict_client.get("/api/admin/workspace-rules",
                                    headers=admin)).status_code == 200
    assert (await strict_client.put("/api/admin/workspace-rules", json=RULES,
                                    headers=admin)).status_code == 403
    assert (await strict_client.get(
        "/api/admin/workspace-rules",
        headers=_h(ws, "rules.rm@eko.co.in", "rm"))).status_code == 403


# ---- who may join -----------------------------------------------------------------

async def test_the_domain_rule_decides_who_can_enter(strict_client, ws):
    await _member(ws, "friend@gmail.com", UserRole.RM)
    friend = _h(ws, "friend@gmail.com", "rm")
    r = await strict_client.get("/api/csps/search?q=ab", headers=friend)
    assert r.status_code == 403, "gmail.com is not allowed in this workspace"

    r = await strict_client.put(
        "/api/admin/workspace-rules",
        json={**RULES, "allowed_email_domains": ["eko.co.in", "gmail.com"]},
        headers=_h(ws, OWNER, "super_admin"))
    assert r.status_code == 200
    r = await strict_client.get("/api/csps/search?q=ab", headers=friend)
    assert r.status_code != 403, "allowed once the Owner adds the domain"


async def test_adding_a_member_follows_the_workspaces_domains(strict_client, ws):
    owner = _h(ws, OWNER, "super_admin")
    r = await strict_client.post("/api/admin/access/grant", headers=owner, json={
        "email": "someone@abc.com", "name": "Someone", "role": "rm"})
    assert r.status_code == 400 and "@eko.co.in" in r.text
    await strict_client.put("/api/admin/workspace-rules", json=RULES,
                            headers=owner)
    r = await strict_client.post("/api/admin/access/grant", headers=owner, json={
        "email": "someone@abc.com", "name": "Someone", "role": "rm"})
    assert r.status_code == 201, r.text


async def test_admins_add_members_only_when_the_owner_allows(strict_client, ws):
    await _member(ws, "rules.admin2@eko.co.in", UserRole.ADMIN)
    admin = _h(ws, "rules.admin2@eko.co.in", "admin")
    grant = {"email": "new.rm@eko.co.in", "name": "New RM", "role": "rm"}
    r = await strict_client.post("/api/admin/access/grant", headers=admin,
                                 json=grant)
    assert r.status_code == 403, "Owner only by default"

    await strict_client.put("/api/admin/workspace-rules", json=RULES,
                            headers=_h(ws, OWNER, "super_admin"))
    r = await strict_client.post("/api/admin/access/grant", headers=admin,
                                 json=grant)
    assert r.status_code == 201, r.text
    r = await strict_client.post("/api/admin/access/grant", headers=admin,
                                 json={**grant, "email": "boss@eko.co.in",
                                       "role": "super_admin"})
    assert r.status_code == 403, "an Admin never adds a Super Admin"
    r = await strict_client.post("/api/admin/access/revoke", headers=admin,
                                 json={"email": OWNER, "role": "super_admin"})
    assert r.status_code == 403, "nor removes one"


# ---- sign-in length and sign-off ----------------------------------------------------

async def test_a_sign_in_lasts_as_long_as_the_workspace_says():
    from app.routers.auth_router import _issue_tokens
    ws = SimpleNamespace(id=uuid.uuid4(), slug="x", name="X",
                         settings={"session_hours": 3})
    user = SimpleNamespace(email="a@eko.co.in", name="A")
    member = SimpleNamespace(role=UserRole.RM)
    out = _issue_tokens(user, member, ws)
    claims = jwt_service.decode_token(out.access_token)
    left = claims["exp"] - datetime.now(timezone.utc).timestamp()
    assert 3 * 3600 - 60 < left <= 3 * 3600


async def test_a_new_sign_off_goes_onto_the_wordings(strict_client, ws):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        with workspace(ws.id):
            s.add_all([
                MessageTemplate(purpose="data_request", name="Ask",
                                channel_kind="whatsapp", languages=["en"],
                                body="Namaste {name}, please confirm.\n\n— Team",
                                is_builtin=True, active=True),
                MessageTemplate(purpose="custom", name="Plain",
                                channel_kind="email", languages=["en"],
                                body="No sign-off here.", is_builtin=False,
                                active=True)])
            await s.commit()
    r = await strict_client.put("/api/admin/workspace-rules", json=RULES,
                                headers=_h(ws, OWNER, "super_admin"))
    body = r.json()
    assert body["wordings_resigned"] == ["Ask"]
    assert "Meta's approval" in body["note"]
    async with async_session_factory() as s:
        with workspace(ws.id):
            bodies = {t.name: t.body for t in (await s.execute(
                select(MessageTemplate))).scalars()}
    assert bodies["Ask"].endswith("— Team Patna Pilot")
    assert bodies["Plain"] == "No sign-off here."


async def test_resign_only_touches_a_last_sign_off_line():
    assert workspace_rules.resign("Hi\n\n— Team Eko", "X") == "Hi\n\n— X"
    assert workspace_rules.resign("Hi\n— Team Eko\n\n", "X") == "Hi\n— X"
    assert workspace_rules.resign("Hi — not a sign-off", "X") is None
    assert workspace_rules.resign("Hi\n\n— X", "X") is None
