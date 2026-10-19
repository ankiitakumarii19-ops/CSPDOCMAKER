"""A brand-new workspace's Owner asks the chat how to set up (No. 117).

The workspace is created exactly as sign-up creates one — nothing seeded,
empty Knowledge Base — and its Owner signs in to it. The chat must still
guide them: the checklist, how to add a data source, and the honest note
that a new workspace's CSPs are not loaded yet.
"""

import uuid

import pytest
from sqlalchemy import text

from app.services import assistant_tools, jwt_service, workspace_service
from app.services import workspace_setup
from app.workspace_context import all_workspaces

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER = "newowner.setup@eko.co.in"


@pytest.fixture(autouse=True)
def _fresh_redis_client(monkeypatch):
    monkeypatch.setattr(assistant_tools, "_redis", None)


@pytest.fixture
async def new_ws(migrated_db, monkeypatch):
    from app.database import async_session_factory
    monkeypatch.setattr(workspace_setup, "service_account_email",
                        lambda: "bot@project.iam.gserviceaccount.com")
    async with async_session_factory() as s:
        ws = await workspace_service.create_workspace(
            s, f"Patna Pilot {uuid.uuid4().hex[:6]}", OWNER, "New Owner")
        await s.commit()
        yield ws
        with all_workspaces():
            await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                            .bindparams(w=ws.id))
            await s.commit()


def _owner(ws):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": OWNER, "email": OWNER, "role": "super_admin",
        "name": "New Owner", "ws": str(ws.id)})}


async def _ask(client, ws, question):
    r = await client.post("/api/assistant/chat", headers=_owner(ws),
                          json={"messages": [{"role": "user",
                                              "content": question}]})
    assert r.status_code == 200, r.text
    return r.json()


async def test_the_chat_opens_with_the_checklist(strict_client, new_ws):
    r = await strict_client.get("/api/assistant/setup", headers=_owner(new_ws))
    body = r.json()
    assert body["owner"] is True and body["complete"] is False
    assert body["done"] == 0
    steps = {s["key"]: s for s in body["cards"][0]["steps"]}
    assert steps["team"]["detail"] == "Only you can sign in so far."
    assert steps["sheet"]["status"] == "todo"
    assert steps["records"]["status"] == "blocked"
    assert steps["knowledge"]["status"] == "optional"


@pytest.mark.parametrize("question", [
    "how to setup", "how do I set up my workspace", "what should I do first",
])
async def test_how_to_set_up_gives_the_checklist(strict_client, new_ws,
                                                 question):
    body = await _ask(strict_client, new_ws, question)
    assert body["cards"][0]["type"] == "setup", question
    assert body["reply"].startswith("**Workspace setup: 0 of 5 essential")
    assert "Next: **Connect your CSP Google Sheet**" in body["reply"]


@pytest.mark.parametrize("question", [
    "how to add data source", "add data source", "data source kaise add kare",
    "where do I add my CSP data", "can I add an excel file",
])
async def test_adding_a_data_source_is_explained(strict_client, new_ws,
                                                 question):
    body = await _ask(strict_client, new_ws, question)
    reply = body["reply"]
    assert "bot@project.iam.gserviceaccount.com" in reply, question
    assert "connect sheet <link> tab <tab name>" in reply
    assert "Excel or CSV files cannot be connected" in reply
    assert "does not yet load its CSPs" in reply


async def test_why_no_csps_is_answered_honestly(strict_client, new_ws):
    body = await _ask(strict_client, new_ws, "why are there no CSPs?")
    assert "only Eko's sheet is read" in body["reply"]
