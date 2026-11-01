# -*- coding: utf-8 -*-
"""Profile pictures (No. 171): optional, your own only, initials without."""

import io

import pytest
from PIL import Image
from sqlalchemy import text

from app.services import jwt_service
from tests.conftest import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _auth(email, role="rm"):
    token = jwt_service.create_access_token(
        {"sub": email, "role": role, "name": email.split("@")[0]})
    return {"Authorization": f"Bearer {token}"}


def _png(size=(800, 400), mode="RGBA"):
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else "red").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
async def clean(db):
    await db.execute(text("TRUNCATE user_photos"))
    await db.commit()
    yield db


async def _upload(client, email, data=None, name="me.png"):
    return await client.put("/api/profile/photo", headers=_auth(email),
                            files={"file": (name, data or _png(), "image/png")})


async def test_no_picture_means_initials(client, clean):
    r = await client.get("/api/profile/photo/ankita@eko.co.in",
                         headers=_auth("ankita@eko.co.in"))
    assert r.status_code == 404


async def test_upload_is_made_square_and_small(client, clean):
    r = await _upload(client, "Ankita@eko.co.in")
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "ankita@eko.co.in"
    got = await client.get("/api/profile/photo/ankita@eko.co.in",
                           headers=_auth("ankita@eko.co.in"))
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(got.content)) as image:
        assert image.size == (256, 256)
        # Transparent parts went white, not black.
        assert min(image.getpixel((0, 0))) > 100


async def test_change_then_remove(client, clean):
    first = (await _upload(client, "rm1@eko.co.in")).json()["version"]
    second = (await _upload(client, "rm1@eko.co.in",
                            _png((300, 300), "RGB"))).json()["version"]
    assert first != second
    r = await client.delete("/api/profile/photo", headers=_auth("rm1@eko.co.in"))
    assert r.json()["removed"] is True
    assert (await client.get("/api/profile/photo/rm1@eko.co.in",
                             headers=_auth("rm1@eko.co.in"))).status_code == 404


async def test_a_colleague_in_the_workspace_sees_it(client, clean):
    await _upload(client, "rm2@eko.co.in")
    r = await client.get("/api/profile/photo/rm2@eko.co.in",
                         headers=_auth("admin2@eko.co.in", "admin"))
    assert r.status_code == 200


async def test_someone_outside_the_workspace_is_not_shown(client, clean):
    await _upload(client, "stranger@elsewhere.com")
    # The stranger was made a member by the test client; take that away.
    await clean.execute(text(
        "DELETE FROM workspace_members WHERE email = 'stranger@elsewhere.com' "
        "AND workspace_id = :w").bindparams(w=DEFAULT_WORKSPACE_ID))
    await clean.commit()
    r = await client.get("/api/profile/photo/stranger@elsewhere.com",
                         headers=_auth("admin2@eko.co.in", "admin"))
    assert r.status_code == 404


@pytest.mark.parametrize("data,name", [(b"", "x.png"), (b"not an image", "x.png")])
async def test_a_bad_file_says_why(client, clean, data, name):
    r = await client.put("/api/profile/photo", headers=_auth("rm3@eko.co.in"),
                         files={"file": (name, data, "image/png")})
    assert r.status_code == 400 and r.json()["detail"]


async def test_signed_out_cannot_upload(client, clean):
    r = await client.put("/api/profile/photo",
                         files={"file": ("x.png", _png(), "image/png")})
    assert r.status_code in (401, 403)
