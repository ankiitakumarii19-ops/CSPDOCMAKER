"""The chat guides a Workspace Owner through setup (tracker No. 117).

Asked questions are answered with the workspace's real setup state; the
chat only PROPOSES work, which runs once, when the Owner presses Do it,
through the setup screens' own server functions, and is audited. Google is
never called: the sheet calls are replaced here.
"""

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.agent import AgentState
from app.models.audit_log import AuditLog
from app.models.data_source import DataSource
from app.models.messaging import MessageChannel, MessageTemplate
from app.models.workspace_member import WorkspaceMember
from app.services import assistant_tools, workspace_setup
from app.services import sheet_admin_service as sheets

pytestmark = pytest.mark.asyncio(loop_scope="session")

SHEET = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
URL = f"https://docs.google.com/spreadsheets/d/{SHEET}/edit#gid=0"


def _auth(role, who=None):
    from app.services import jwt_service
    email = f"{who or role}@eko.co.in"
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": email, "email": email, "role": role,
        "name": (who or role).title()})}


@pytest.fixture(autouse=True)
def _fresh_redis_client(monkeypatch):
    monkeypatch.setattr(assistant_tools, "_redis", None)


@pytest.fixture
def db(migrated_db, monkeypatch):
    """A clean setup state; nothing reaches Google."""
    from app.routers import access_router

    async def no_sheet(**kw):
        return None
    monkeypatch.setattr(access_router, "_grant_in_sheet", no_sheet)
    monkeypatch.setattr(sheets, "list_tabs",
                        lambda sid: [{"title": "KOData"}, {"title": "INFO"}])
    monkeypatch.setattr(workspace_setup, "service_account_email",
                        lambda: "bot@project.iam.gserviceaccount.com")
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as s:
        # The seeded rows other test files rely on are kept aside and put
        # back afterwards, so this file can start from an empty workspace.
        for t in _KEPT:
            s.execute(text(f"DROP TABLE IF EXISTS kept_{t}"))
            s.execute(text(f"CREATE TABLE kept_{t} AS SELECT * FROM {t}"))
            s.execute(text(f"DELETE FROM {t}"))
        s.execute(text("TRUNCATE audit_logs"))
        s.execute(text("DELETE FROM workspace_members WHERE email LIKE "
                       "'%.setup@eko.co.in'"))
        s.commit()
        try:
            yield s
        finally:
            s.rollback()
            for t in _KEPT:
                s.execute(text(f"DELETE FROM {t}"))
                s.execute(text(f"INSERT INTO {t} SELECT * FROM kept_{t}"))
                s.execute(text(f"DROP TABLE kept_{t}"))
            s.execute(text("DELETE FROM workspace_members WHERE email LIKE "
                           "'%.setup@eko.co.in'"))
            s.commit()
    engine.dispose()


_KEPT = ("data_sources", "message_templates", "message_channels",
         "agent_states", "document_templates")


async def _reply(client, question, role="super_admin", who="owner"):
    r = await client.post("/api/assistant/chat", headers=_auth(role, who),
                          json={"messages": [{"role": "user",
                                              "content": question}]})
    assert r.status_code == 200, r.text
    return r.json()


async def _do(client, card, who="owner"):
    return await client.post(f"/api/assistant/actions/{card['id']}/run",
                             headers=_auth("super_admin", who))


# ---- the checklist -------------------------------------------------------------

async def test_setup_status_lists_every_step_honestly(client, db):
    body = await _reply(client, "setup status")
    [card] = body["cards"]
    assert card["type"] == "setup"
    steps = {s["key"]: s for s in card["steps"]}
    assert steps["sheet"]["status"] == "todo"
    assert "bot@project.iam.gserviceaccount.com" in steps["sheet"]["how"]
    assert steps["wordings"]["status"] == "todo"
    assert steps["channel"]["status"] == "todo"
    assert steps["templates"]["status"] == "todo"
    assert body["reply"].startswith("**Workspace setup: ") and " of 5 essential" in body["reply"]
    for q in ("what's left?", "what is the issue", "getting started",
              "setup kya baki hai"):
        assert (await _reply(client, q))["cards"][0]["type"] == "setup", q


async def test_an_unreadable_sheet_is_reported_as_the_problem(client, db,
                                                              monkeypatch):
    db.add(DataSource(name="CSPs", kind="google_sheet", purpose="records",
                      connection={"spreadsheet_id": SHEET, "tab": "KOData"},
                      column_map={}))
    db.commit()

    def refused(sid):
        raise sheets.SheetAdminError("Could not open that spreadsheet: "
                                     "HttpError 403")
    monkeypatch.setattr(sheets, "list_tabs", refused)
    body = await _reply(client, "setup status")
    sheet = {s["key"]: s for s in body["cards"][0]["steps"]}["sheet"]
    assert sheet["status"] == "problem" and "403" in sheet["detail"]
    assert "Fix first" in body["reply"]


async def test_the_chat_opens_with_the_checklist_for_an_owner_only(client, db):
    r = await client.get("/api/assistant/setup", headers=_auth("super_admin",
                                                                "owner"))
    body = r.json()
    assert body["owner"] is True and body["complete"] is False
    assert body["cards"][0]["type"] == "setup"
    r = await client.get("/api/assistant/setup", headers=_auth("rm", "rm1"))
    assert r.json() == {"owner": False, "complete": True}


async def test_admins_get_how_to_but_not_actions(client, db):
    body = await _reply(client, "which email do I share my sheet with",
                        role="admin")
    assert "bot@project.iam.gserviceaccount.com" in body["reply"]
    body = await _reply(client, "add the email channel", role="admin")
    assert body["reply"].startswith("Only the Workspace Owner")
    assert body["cards"] == []


async def test_a_question_about_a_csp_is_not_taken_for_setup(client, db):
    body = await _reply(client, "what is the problem with 1A910001")
    assert all(c["type"] != "setup" for c in body["cards"])


# ---- actions: proposed, then done once on Do it ------------------------------------

async def test_adding_a_member_needs_do_it_and_is_audited(client, db):
    body = await _reply(client, "add rm priya.sharma.setup@eko.co.in")
    [card] = body["cards"]
    assert card["type"] == "action" and card["kind"] == "add_member"
    assert db.execute(select(WorkspaceMember).where(
        WorkspaceMember.email == "priya.sharma.setup@eko.co.in")).first() \
        is None, "nothing is changed before Do it"

    r = await _do(client, card)
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    db.expire_all()
    member = db.execute(select(WorkspaceMember).where(
        WorkspaceMember.email == "priya.sharma.setup@eko.co.in")).scalars().one()
    assert member.role.value == "rm" and member.name == "Priya Sharma Setup"
    audit = db.execute(select(AuditLog).where(
        AuditLog.action == "assistant_setup_action")).scalars().one()
    assert audit.result == "success"
    assert (await _do(client, card)).status_code == 404, "done once only"


async def test_member_requests_that_cannot_be_done(client, db):
    body = await _reply(client, "add rm someone.setup@gmail.com")
    assert "cannot be added" in body["reply"] and body["cards"] == []
    body = await _reply(client, "add amit.setup@eko.co.in")
    assert body["reply"].startswith("As what should amit.setup@eko.co.in")
    assert body["suggestions"] == ["add rm amit.setup@eko.co.in",
                                   "add admin amit.setup@eko.co.in"]


async def test_only_the_proposer_can_press_do_it(client, db):
    [card] = (await _reply(client, "add admin neha.setup@eko.co.in"))["cards"]
    assert (await _do(client, card, who="other")).status_code == 404
    r = await _do(client, card)
    assert r.status_code == 200 and r.json()["ok"], \
        "someone else's press did not use it up"


async def test_cancel_changes_nothing(client, db):
    [card] = (await _reply(client, "add rm ravi.setup@eko.co.in"))["cards"]
    r = await client.delete(f"/api/assistant/actions/{card['id']}",
                            headers=_auth("super_admin", "owner"))
    assert r.status_code == 200
    assert (await _do(client, card)).status_code == 404
    assert db.execute(select(WorkspaceMember).where(
        WorkspaceMember.email == "ravi.setup@eko.co.in")).first() is None


async def test_message_wordings_are_signed_with_the_workspace(client, db):
    [card] = (await _reply(client, "create the message wordings"))["cards"]
    r = await _do(client, card)
    assert r.json()["ok"] and "Added 3" in r.json()["message"]
    db.expire_all()
    bodies = [t.body for t in db.execute(select(MessageTemplate)).scalars()]
    assert len(bodies) == 3
    assert all("Team Eko SBI Kiosk CSP" in b or "— Team " in b for b in bodies)
    assert not any(b.rstrip().endswith("— Team") for b in bodies)
    assert r.json()["next"]["title"] != "Message wordings", "done is not next"


async def test_the_email_channel_is_added_once(client, db):
    [card] = (await _reply(client, "add the email channel"))["cards"]
    assert (await _do(client, card)).json()["ok"]
    db.expire_all()
    [channel] = db.execute(select(MessageChannel)).scalars().all()
    assert channel.kind == "email" and channel.is_default
    body = await _reply(client, "add the email channel")
    assert body["reply"].startswith("There is already an email channel")


async def test_an_agent_is_turned_on(client, db):
    [card] = (await _reply(client, "turn on the communication agent"))["cards"]
    assert card["kind"] == "enable_agent"
    assert (await _do(client, card)).json()["ok"]
    db.expire_all()
    state = db.execute(select(AgentState).where(
        AgentState.agent_key == "communication")).scalars().one()
    assert state.enabled
    body = await _reply(client, "turn on the communication agent")
    assert body["reply"] == "The Communication agent is already on."
    assert body["cards"] == []


async def test_a_sheet_is_checked_before_it_is_offered(client, db, monkeypatch):
    body = await _reply(client, f"connect sheet {URL}")
    assert "Which tab holds your CSPs?" in body["reply"]
    assert f"connect sheet {SHEET} tab KOData" in body["suggestions"]

    body = await _reply(client, f"connect sheet {URL} tab Nope")
    assert body["reply"].startswith("There is no tab called 'Nope'")

    [card] = (await _reply(client, f"connect sheet {URL} tab KOData"))["cards"]
    assert card["kind"] == "connect_sheet"
    assert "does not yet load" in card["extra"][0]
    assert (await _do(client, card)).json()["ok"]
    db.expire_all()
    [source] = db.execute(select(DataSource)).scalars().all()
    assert source.connection == {"spreadsheet_id": SHEET, "tab": "KOData"}

    def refused(sid):
        raise sheets.SheetAdminError("Could not open that spreadsheet: 403")
    monkeypatch.setattr(sheets, "list_tabs", refused)
    body = await _reply(client, f"connect sheet {URL} tab KOData")
    assert body["reply"].startswith("I could not open that sheet")
    assert "bot@project.iam.gserviceaccount.com" in body["reply"]
    assert body["cards"] == []


async def test_actions_are_the_owners_alone(client, db):
    r = await client.post("/api/assistant/actions/" + "0" * 32 + "/run",
                          headers=_auth("admin"))
    assert r.status_code == 403
