"""Setup → Display (No. 228): the Super Admin picks the look for everyone."""

import uuid

import pytest
from sqlalchemy import text

from app.services import jwt_service, settings_catalog, workspace_service, workspace_settings
from app.workspace_context import all_workspaces

pytestmark = pytest.mark.asyncio(loop_scope="session")
OWNER = "display.owner@eko.co.in"


def test_nine_looks_and_eko_keeps_its_own():
    s = settings_catalog.BY_KEY["ui_theme"]
    assert len(s.choices) == 9 and s.choices[0] == "classic"
    from app.config import Settings
    assert Settings.model_fields["ui_theme"].default == "classic"


async def test_the_super_admin_picks_a_look_everyone_gets(strict_client, migrated_db):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        ws = await workspace_service.create_workspace(
            s, f"Display {uuid.uuid4().hex[:6]}", OWNER, "Owner")
        await s.commit()
    h = {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": OWNER, "email": OWNER, "role": "super_admin", "name": "O",
        "ws": str(ws.id)})}
    try:
        me = (await strict_client.get("/api/me/access", headers=h)).json()
        assert me["look"]["theme"] == "classic"
        r = await strict_client.put("/api/admin/settings/ui_theme",
                                    json={"value": "ocean"}, headers=h)
        assert r.status_code == 200, r.text
        me = (await strict_client.get("/api/me/access", headers=h)).json()
        assert me["look"]["theme"] == "ocean"
        r = await strict_client.put("/api/admin/settings/ui_theme",
                                    json={"value": "neon"}, headers=h)
        assert r.status_code == 400
    finally:
        async with async_session_factory() as s:
            with all_workspaces():
                await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                                .bindparams(w=ws.id))
                await s.commit()
        workspace_settings.forget()


def test_fifteen_design_styles_and_eko_keeps_standard():
    s = settings_catalog.BY_KEY["ui_style"]
    assert len(s.choices) == 15 and s.choices[0] == "standard"
    for name in ("clay", "neumorph", "glass", "maximal", "minimal", "brutal"):
        assert name in s.choices
    from app.config import Settings
    assert Settings.model_fields["ui_style"].default == "standard"


async def test_the_design_style_reaches_every_page(strict_client, migrated_db):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        ws = await workspace_service.create_workspace(
            s, f"Style {uuid.uuid4().hex[:6]}", OWNER, "Owner")
        await s.commit()
    h = {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": OWNER, "email": OWNER, "role": "super_admin", "name": "O",
        "ws": str(ws.id)})}
    try:
        assert (await strict_client.get("/api/me/access", headers=h)).json()[
            "look"]["style"] == "standard"
        r = await strict_client.put("/api/admin/settings/ui_style",
                                    json={"value": "clay"}, headers=h)
        assert r.status_code == 200, r.text
        assert (await strict_client.get("/api/me/access", headers=h)).json()[
            "look"]["style"] == "clay"
    finally:
        async with async_session_factory() as s:
            with all_workspaces():
                await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                                .bindparams(w=ws.id))
                await s.commit()
        workspace_settings.forget()
