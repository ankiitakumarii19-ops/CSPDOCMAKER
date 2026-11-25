# -*- coding: utf-8 -*-
"""Each person's own look (No. 240, SaaS upgrade Stage 2).

Brief checks covered here: 1 two people in one workspace keep different
looks; 2 one person's font never reaches another; 9 the look is still there
after signing out and in (a new sign-in = a new token); 10 reset works.
"""

import pytest
from sqlalchemy import text

from app.services import jwt_service, my_look

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _auth(email, role="rm"):
    # A new token each call: the same as signing in again.
    token = jwt_service.create_access_token(
        {"sub": email, "role": role, "name": email.split("@")[0]})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def clean(db):
    await db.execute(text("TRUNCATE user_preferences"))
    await db.commit()
    yield db


async def _save(client, email, look, role="rm"):
    return await client.put("/api/profile/appearance", headers=_auth(email, role),
                            json={"appearance": look})


async def _mine(client, email, role="rm"):
    r = await client.get("/api/profile/appearance", headers=_auth(email, role))
    assert r.status_code == 200, r.text
    return r.json()["appearance"]


# ---- the brief's checks -----------------------------------------------------

async def test_nothing_saved_means_the_workspace_look(client, clean):
    r = await client.get("/api/profile/appearance", headers=_auth("rm1@eko.co.in"))
    assert r.status_code == 200
    body = r.json()
    assert body["appearance"] == {}
    assert {o["key"] for o in body["options"]} == set(my_look.BY_KEY)


async def test_two_people_keep_different_looks(client, clean):
    a = await _save(client, "rm1@eko.co.in",
                    {"mode": "dark", "accent": "#7c3aed", "density": "compact"})
    b = await _save(client, "admin1@eko.co.in",
                    {"mode": "light", "accent": "#2563eb", "cards": "square"}, "admin")
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    assert await _mine(client, "rm1@eko.co.in") == {
        "mode": "dark", "accent": "#7c3aed", "density": "compact"}
    assert await _mine(client, "admin1@eko.co.in", "admin") == {
        "mode": "light", "accent": "#2563eb", "cards": "square"}


async def test_one_persons_font_does_not_reach_another(client, clean):
    await _save(client, "rm1@eko.co.in", {"font": "inter"})
    await _save(client, "rm2@eko.co.in", {"font": "lato", "text_size": 110})
    r = await client.patch("/api/profile/appearance", headers=_auth("rm1@eko.co.in"),
                           json={"appearance": {"font": "poppins"}})
    assert r.status_code == 200
    assert (await _mine(client, "rm1@eko.co.in"))["font"] == "poppins"
    assert await _mine(client, "rm2@eko.co.in") == {"font": "lato", "text_size": 110}


async def test_still_there_after_signing_in_again(client, clean):
    await _save(client, "rm1@eko.co.in", {"scale": 120, "high_contrast": True})
    # _mine makes a fresh token: a new sign-in.
    assert await _mine(client, "RM1@eko.co.in") == {"scale": 120, "high_contrast": True}


async def test_reset_goes_back_to_the_workspace_look(client, clean):
    await _save(client, "rm1@eko.co.in", {"mode": "dark", "font": "roboto"})
    await _save(client, "rm2@eko.co.in", {"mode": "dark"})
    r = await client.delete("/api/profile/appearance", headers=_auth("rm1@eko.co.in"))
    assert r.status_code == 200 and r.json()["appearance"] == {}
    assert await _mine(client, "rm1@eko.co.in") == {}
    assert await _mine(client, "rm2@eko.co.in") == {"mode": "dark"}


async def test_patch_null_means_as_the_workspace_has_it(client, clean):
    await _save(client, "rm1@eko.co.in", {"mode": "dark", "font": "roboto"})
    r = await client.patch("/api/profile/appearance", headers=_auth("rm1@eko.co.in"),
                           json={"appearance": {"font": None, "mode": "light"}})
    assert r.json()["appearance"] == {"mode": "light"}


async def test_changes_are_recorded_without_the_values(client, clean):
    await clean.execute(text("DELETE FROM audit_logs WHERE action LIKE 'appearance%'"))
    await clean.commit()
    await _save(client, "rm1@eko.co.in", {"mode": "dark"})
    await client.delete("/api/profile/appearance", headers=_auth("rm1@eko.co.in"))
    rows = (await clean.execute(text(
        "SELECT action, metadata_json FROM audit_logs "
        "WHERE action LIKE 'appearance%' ORDER BY created_at"))).all()
    assert [r[0] for r in rows] == ["appearance_change", "appearance_reset"]
    assert rows[0][1]["changed"] == ["mode"]


async def test_every_role_may_set_their_own(client, clean):
    for email, role in [("rm9@eko.co.in", "rm"), ("ad9@eko.co.in", "admin"),
                        ("sa9@eko.co.in", "super_admin")]:
        r = await _save(client, email, {"density": "spacious"}, role)
        assert r.status_code == 200, (role, r.text)


async def test_signed_out_is_refused(client, clean):
    r = await client.get("/api/profile/appearance")
    assert r.status_code in (401, 403)


# ---- what is refused, and why -------------------------------------------------

@pytest.mark.parametrize("look,words", [
    ({"colour_of_doom": "#000000"}, "not something you can change"),
    ({"mode": "purple"}, "not one of the choices"),
    ({"font": "comic_sans"}, "not one of the choices"),
    ({"text_size": 300}, "between 85% and 130%"),
    ({"text_size": 87}, "steps of 5"),
    ({"scale": "big"}, "whole number"),
    ({"high_contrast": "yes"}, "on or off"),
    ({"accent": "green"}, "colour like"),
    ({"background": "#111111"}, "too dark for the normal text"),
    ({"card": "#333333"}, "too dark for the normal text"),
    ({"menu": "#f8fafc"}, "too light for the menu"),
    ({"button": "#ffff00"}, "too light for white"),
])
async def test_an_unreadable_or_unknown_choice_is_refused(client, clean, look, words):
    r = await _save(client, "rm1@eko.co.in", look)
    assert r.status_code == 400
    assert words in r.json()["detail"]
    # Nothing half-saved.
    assert await _mine(client, "rm1@eko.co.in") == {}


async def test_eko_green_is_allowed_with_a_hint(client, clean):
    r = await _save(client, "rm1@eko.co.in", {"accent": "#00B259"})
    assert r.status_code == 200
    assert r.json()["appearance"] == {"accent": "#00b259"}
    assert any("harder to read" in w for w in r.json()["warnings"])


async def test_contrast_matches_wcag():
    assert my_look.contrast("#000000", "#ffffff") == 21.0
    assert my_look.contrast("#ffffff", "#ffffff") == 1.0
