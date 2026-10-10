# -*- coding: utf-8 -*-
"""Editing the sheets the system reads.

This is the one screen in the product that changes the data every other
screen is derived from, and the one place where a click destroys something
no code here can bring back. So the tests are about the two ways that goes
wrong: writing to the wrong place, and the wrong person being able to.

Nothing here talks to Google. The parts that do are thin wrappers around
the API; what is worth pinning is the addressing and the guards, because
an off-by-one in a column letter silently overwrites the wrong field on a
real person's row.
"""

import pytest

from app.services import sheet_admin_service as sa
from app.services.sheet_admin_service import SheetAdminError

pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---- addressing ---------------------------------------------------------
#
# These produce the range an edit is written to. Every one of them being
# right is the difference between correcting a mobile number and
# overwriting a branch code.

@pytest.mark.parametrize("index,letter", [
    (0, "A"), (1, "B"), (25, "Z"),
    (26, "AA"), (27, "AB"), (51, "AZ"), (52, "BA"),
    (701, "ZZ"), (702, "AAA"),
])
def test_column_letters(index, letter):
    assert sa.column_letter(index) == letter


def test_the_csp_sheets_widest_column_resolves():
    """The CSP tab has 23 columns; the INFO tab's rows are wider still."""
    assert sa.column_letter(22) == "W"
    assert sa.column_letter(25) == "Z"


@pytest.mark.parametrize("tab,quoted", [
    ("CSPData", "CSPData"),
    ("INFO", "INFO"),
    ("Sheet_1", "Sheet_1"),
    ("My Tab", "'My Tab'"),
    ("Q1 2026", "'Q1 2026'"),
    ("it's", "'it''s'"),
])
def test_tab_names_are_quoted_when_they_need_it(tab, quoted):
    """An unquoted tab name with a space addresses nothing, or worse,
    something else."""
    assert sa._quote_tab(tab) == quoted


# ---- the header row is not data -----------------------------------------

async def test_the_header_row_cannot_be_edited():
    """Row 1 names the columns every other part of the system matches on.

    Renaming one there would not look like a break — the sync would simply
    stop seeing that field, and documents would start coming out missing a
    value with nothing to say why.
    """
    with pytest.raises(SheetAdminError, match="header"):
        sa.update_row("any-sheet", "CSPData", 1, {"CSP Name": "x"})


async def test_the_header_row_cannot_be_deleted():
    with pytest.raises(SheetAdminError, match="header"):
        sa.delete_row("any-sheet", "CSPData", 1)


@pytest.mark.parametrize("row_number", [0, -1, -99])
async def test_a_row_number_below_the_first_row_is_refused(row_number):
    with pytest.raises(SheetAdminError):
        sa.update_row("any-sheet", "CSPData", row_number, {"a": "b"})


# ---- who may do this ----------------------------------------------------

SHEET_PATHS = [
    ("GET", "/api/admin/sheets"),
    ("GET", "/api/admin/sheets/00000000-0000-0000-0000-000000000000/tabs/CSPData"),
]


def _token(role: str) -> str:
    from app.services import jwt_service
    return jwt_service.create_access_token({
        "sub": f"{role}@eko.co.in", "email": f"{role}@eko.co.in",
        "role": role, "name": role.title(),
    })


def _auth(role: str) -> dict:
    return {"Authorization": f"Bearer {_token(role)}"}


@pytest.mark.parametrize("method,path", SHEET_PATHS)
async def test_signing_in_is_required(client, method, path):
    response = await client.request(method, path)
    assert response.status_code in (401, 403), (
        f"{path} was reachable without signing in")


@pytest.mark.parametrize("method,path", SHEET_PATHS)
@pytest.mark.parametrize("role", ["rm", "admin"])
async def test_only_the_owner_may_touch_the_sheets(client, method, path, role):
    """An Admin configures how the system behaves. This changes the data it
    behaves on, which is a different job and a different door."""
    response = await client.request(method, path, headers=_auth(role))
    assert response.status_code == 403, (
        f"a {role} reached {path} — it is Super Admin only")


async def test_deleting_a_row_is_owner_only(client):
    response = await client.delete(
        "/api/admin/sheets/00000000-0000-0000-0000-000000000000"
        "/tabs/CSPData/rows/2",
        headers=_auth("admin"))
    assert response.status_code == 403, (
        "an Admin could delete a row from the live sheet")


async def test_the_owner_gets_past_the_door(client):
    """Not a 403. What it does next depends on Google, so anything but a
    permission refusal is what this checks."""
    response = await client.get("/api/admin/sheets", headers=_auth("super_admin"))
    assert response.status_code != 403


# ---- unknown columns are reported, not created --------------------------

async def test_an_unknown_column_is_reported_rather_than_invented(monkeypatch):
    """Adding a column changes what every reader of the sheet sees. That is
    a deliberate act, not the consequence of a typo in a field name."""
    monkeypatch.setattr(sa, "_header",
                        lambda sheet, tab: ["CSP Code", "CSP Name"])
    sent = {}
    monkeypatch.setattr(sa, "_service", lambda: _FakeService(sent))

    written, unknown = sa.update_row(
        "sheet", "CSPData", 5,
        {"CSP Name": "Someone", "Nickname": "Nobody"})

    assert written == {"CSP Name": "Someone"}
    assert unknown == ["Nickname"]
    assert "Nickname" not in str(sent), "a column was invented"


class _FakeService:
    """Just enough of the Sheets client to capture what would be sent."""

    def __init__(self, sink):
        self._sink = sink

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def batchUpdate(self, **kwargs):            # noqa: N802 — Google's name
        self._sink.update(kwargs)
        return self

    def execute(self):
        return {}


# ---- serving a photograph -----------------------------------------------
#
# The Photo column holds a file path, so the screen shows the picture
# rather than the path. The path comes out of a spreadsheet cell, which
# anyone with the sheet can type into — so it is a hostile input, and the
# interesting tests are the ones that try to leave the photos directory.

PHOTO_URL = "/api/admin/sheets/_photo"


@pytest.mark.parametrize("path", [
    "../../.env",
    "../../../../Windows/System32/drivers/etc/hosts",
    "/etc/passwd",
    "C:\CSPDOCMAKER\backend\.env",
    "generated_documents/photos/../../.env",
])
async def test_a_photo_path_cannot_escape_the_photos_directory(client, path):
    """A cell reading '..\..\.env' must not become a file read."""
    response = await client.get(PHOTO_URL, params={"path": path},
                                headers=_auth("super_admin"))
    assert response.status_code in (400, 404), (
        f"{path!r} was not refused — this endpoint can read arbitrary files")
    assert b"SECRET" not in response.content.upper()


async def test_a_non_image_inside_the_directory_is_still_refused(
        client, tmp_path, monkeypatch):
    """Being in the right folder is not enough; it has to be an image."""
    from app.config import get_settings

    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "notes.txt").write_text("not an image")
    monkeypatch.setattr(get_settings(), "document_output_dir", str(tmp_path))

    response = await client.get(PHOTO_URL,
                                params={"path": str(photos / "notes.txt")},
                                headers=_auth("super_admin"))
    assert response.status_code == 400


async def test_a_real_photograph_is_served(client, tmp_path, monkeypatch):
    from app.config import get_settings
    from app.services import template_service

    photos = tmp_path / "photos"
    photos.mkdir()
    target = photos / "1A850076.png"
    target.write_bytes(
        open(template_service.PLACEHOLDER_PHOTO, "rb").read())
    monkeypatch.setattr(get_settings(), "document_output_dir", str(tmp_path))

    response = await client.get(PHOTO_URL, params={"path": str(target)},
                                headers=_auth("super_admin"))
    assert response.status_code == 200
    assert response.content[:4] == b"\x89PNG"


async def test_a_photograph_is_not_public(client):
    response = await client.get(PHOTO_URL, params={"path": "x.png"})
    assert response.status_code in (401, 403)


@pytest.mark.parametrize("role", ["rm", "admin"])
async def test_only_the_owner_may_fetch_a_photograph(client, role):
    response = await client.get(PHOTO_URL, params={"path": "x.png"},
                                headers=_auth(role))
    assert response.status_code == 403
