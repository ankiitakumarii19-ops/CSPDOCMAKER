# -*- coding: utf-8 -*-
"""Organisation branding and each person's notifications (No. 240, Stage 3).

Brief check 3: two organisations can have completely different branding.
Also: the logo is the organisation's own; only its Super Admin changes it;
the workspace may keep colours and font its own; a person may switch off an
optional staff email, never a mandatory one, and the switch only drops them.
"""

import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import text

from app.services import (jwt_service, notification_prefs, workspace_files,
                          workspace_service, workspace_settings)
from app.workspace_context import all_workspaces

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _png(colour="red", size=(1200, 400)):
    buf = io.BytesIO()
    Image.new("RGBA", size, colour).save(buf, "PNG")
    return buf.getvalue()


async def _ws(owner):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        ws = await workspace_service.create_workspace(
            s, f"Brand {uuid.uuid4().hex[:6]}", owner, "Owner")
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
    workspace_files.forget()


def _h(ws, email, role="super_admin"):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": email, "email": email, "role": role, "name": "O",
        "ws": str(ws.id)})}


async def _member(ws, email, role):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        await s.execute(text(
            "INSERT INTO workspace_members (id, workspace_id, email, name, role, "
            "active, created_at, updated_at) VALUES (gen_random_uuid(), :w, :e, "
            "'X', CAST(:r AS user_role), true, now(), now())").bindparams(w=ws.id, e=email, r=role.upper()))
        await s.commit()


async def test_two_organisations_have_completely_different_branding(strict_client, migrated_db):
    a_owner, b_owner = "brand.a@eko.co.in", "brand.b@eko.co.in"
    a, b = await _ws(a_owner), await _ws(b_owner)
    try:
        ha, hb = _h(a, a_owner), _h(b, b_owner)
        for key, value in (("brand_name", "Alpha Docs"), ("brand_color", "#7C3AED"),
                           ("brand_color_2", "#12305C"), ("ui_theme", "royal"),
                           ("ui_style", "glass")):
            r = await strict_client.put(f"/api/admin/settings/{key}", json={"value": value}, headers=ha)
            assert r.status_code == 200, (key, r.text)
        for key, value in (("brand_name", "Beta Papers"), ("brand_color", "#EA580C"),
                           ("ui_theme", "sunset"), ("ui_style", "brutal")):
            r = await strict_client.put(f"/api/admin/settings/{key}", json={"value": value}, headers=hb)
            assert r.status_code == 200, (key, r.text)
        r = await strict_client.put("/api/admin/branding/logo", headers=ha,
                                    files={"file": ("a.png", _png("purple"), "image/png")})
        assert r.status_code == 200, r.text

        la = (await strict_client.get("/api/me/access", headers=ha)).json()["look"]
        lb = (await strict_client.get("/api/me/access", headers=hb)).json()["look"]
        assert (la["name"], la["color"], la["color_2"], la["theme"], la["style"]) == (
            "Alpha Docs", "#7C3AED", "#12305C", "royal", "glass")
        assert (lb["name"], lb["color"], lb["color_2"], lb["theme"], lb["style"]) == (
            "Beta Papers", "#EA580C", "", "sunset", "brutal")
        assert la["logo"] and not lb["logo"]
        assert la["org_name"].startswith("Brand ") and la["org_name"] != lb["org_name"]
        # B cannot see A's logo: its own is "none".
        assert (await strict_client.get("/api/me/logo", headers=hb)).status_code == 404
        got = await strict_client.get("/api/me/logo", headers=ha)
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(got.content)) as image:
            assert image.size[0] <= 600 and image.size[1] <= 200
    finally:
        await _drop(a, b)


async def test_only_the_super_admin_changes_the_logo(strict_client, migrated_db):
    owner, admin, rm = "logo.o@eko.co.in", "logo.a@eko.co.in", "logo.r@eko.co.in"
    ws = await _ws(owner)
    try:
        await _member(ws, admin, "admin")
        await _member(ws, rm, "rm")
        for who, role in ((admin, "admin"), (rm, "rm")):
            r = await strict_client.put("/api/admin/branding/logo", headers=_h(ws, who, role),
                                        files={"file": ("x.png", _png(), "image/png")})
            assert r.status_code == 403, (role, r.text)
        await strict_client.put("/api/admin/branding/logo", headers=_h(ws, owner),
                                files={"file": ("x.png", _png(), "image/png")})
        # Everyone in the workspace sees it.
        assert (await strict_client.get("/api/me/logo", headers=_h(ws, rm, "rm"))).status_code == 200
        r = await strict_client.delete("/api/admin/branding/logo", headers=_h(ws, owner))
        assert r.json()["removed"] is True
        assert (await strict_client.get("/api/me/logo", headers=_h(ws, rm, "rm"))).status_code == 404
    finally:
        await _drop(ws)


@pytest.mark.parametrize("data,name,words", [
    (b"", "x.png", "empty"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "x.svg", "not a picture"),
    (b"not an image", "x.png", "not a picture"),
])
async def test_a_bad_logo_says_why(strict_client, migrated_db, data, name, words):
    owner = "logo.bad@eko.co.in"
    ws = await _ws(owner)
    try:
        r = await strict_client.put("/api/admin/branding/logo", headers=_h(ws, owner),
                                    files={"file": (name, data, "image/png")})
        assert r.status_code == 400 and words in r.json()["detail"]
    finally:
        await _drop(ws)


async def test_a_bad_second_colour_is_refused(strict_client, migrated_db):
    owner = "brand.c@eko.co.in"
    ws = await _ws(owner)
    try:
        r = await strict_client.put("/api/admin/settings/brand_color_2",
                                    json={"value": "blue"}, headers=_h(ws, owner))
        assert r.status_code == 400
    finally:
        await _drop(ws)


async def test_the_workspace_may_keep_colours_and_font_its_own(strict_client, migrated_db):
    owner, rm = "lock.o@eko.co.in", "lock.r@eko.co.in"
    ws = await _ws(owner)
    try:
        await _member(ws, rm, "rm")
        hr = _h(ws, rm, "rm")
        await strict_client.put("/api/profile/appearance", headers=hr,
                                json={"appearance": {"accent": "#7c3aed", "mode": "dark"}})
        r = await strict_client.put("/api/admin/settings/allow_personal_look",
                                    json={"value": False}, headers=_h(ws, owner))
        assert r.status_code == 200, r.text
        v = (await strict_client.get("/api/profile/appearance", headers=hr)).json()
        assert v["own_colours_allowed"] is False
        assert (await strict_client.get("/api/me/access", headers=hr)).json()["look"]["own_colours"] is False
        r = await strict_client.put("/api/profile/appearance", headers=hr,
                                    json={"appearance": {"accent": "#2563eb", "font": "lato",
                                                         "mode": "light", "scale": 120}})
        body = r.json()
        # Colours and font are not taken; the rest is.
        assert body["appearance"] == {"accent": "#7c3aed", "mode": "light", "scale": 120}
        assert any("workspace sets the colours" in w for w in body["warnings"])
    finally:
        await _drop(ws)
        from app.database import async_session_factory
        async with async_session_factory() as s:
            await s.execute(text("DELETE FROM user_preferences WHERE email = :e").bindparams(e=rm))
            await s.commit()


# ---- notifications ------------------------------------------------------------

def _rm(email="rm1@eko.co.in", role="rm"):
    token = jwt_service.create_access_token({"sub": email, "role": role,
                                             "name": email.split("@")[0]})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def clean(db):
    await db.execute(text("TRUNCATE user_preferences"))
    await db.commit()
    yield db


async def test_everything_on_until_switched_off(client, clean):
    r = await client.get("/api/profile/notifications", headers=_rm())
    kinds = {k["key"]: k for k in r.json()["notifications"]}
    assert set(kinds) == set(notification_prefs.BY_KEY)
    for k in kinds.values():
        for ch in k["channels"]:
            if ch["available"]:
                assert ch["on"] is True
    sms = next(c for c in kinds["weekly_health"]["channels"] if c["key"] == "sms")
    assert sms["available"] is False and "SMS" in sms["why"]


async def test_an_optional_email_can_be_switched_off(client, clean):
    r = await client.put("/api/profile/notifications", headers=_rm("sa1@eko.co.in", "super_admin"),
                         json={"notifications": {"weekly_health": {"email": False}}})
    assert r.status_code == 200, r.text
    weekly = next(k for k in r.json()["notifications"] if k["key"] == "weekly_health")
    assert next(c for c in weekly["channels"] if c["key"] == "email")["on"] is False


@pytest.mark.parametrize("body,words", [
    ({"failure_alerts": {"email": False}}, "cannot be switched off"),
    ({"sign_in_codes": {"email": False}}, "cannot be switched off"),
    ({"action_required": {"in_app": False}}, "cannot be switched off"),
    ({"weekly_health": {"sms": False}}, "not sent by sms"),
    ({"pizza": {"email": False}}, "not a notification"),
    ({"weekly_health": {"email": "no"}}, "on or off"),
])
async def test_mandatory_and_unknown_are_refused(client, clean, body, words):
    r = await client.put("/api/profile/notifications", headers=_rm(),
                         json={"notifications": body})
    assert r.status_code == 400 and words in r.json()["detail"]


async def test_switching_off_only_drops_that_person(client, clean):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.config import get_settings
    await client.put("/api/profile/notifications", headers=_rm("sa1@eko.co.in", "super_admin"),
                     json={"notifications": {"daily_contact": {"email": False}}})
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with Session(engine) as s:
            got = notification_prefs.keep_wanted(
                s, "daily_contact", ["SA1@eko.co.in", "sa2@eko.co.in"])
            assert got == ["sa2@eko.co.in"]
            # Mandatory: nobody is dropped, whatever is stored.
            assert notification_prefs.keep_wanted(
                s, "failure_alerts", ["sa1@eko.co.in"]) == ["sa1@eko.co.in"]
            # The weekly email is still theirs.
            assert notification_prefs.keep_wanted(
                s, "weekly_health", ["sa1@eko.co.in"]) == ["sa1@eko.co.in"]
    finally:
        engine.dispose()
