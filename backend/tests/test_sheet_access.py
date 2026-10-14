"""Who may touch which sheet (tracker No. 104).

Decided 14 Oct 2026: RMs and Admins may read and edit the CSP tabs (the
tabs the records and directory sheets are read from); only the Super Admin
may open the access sheet (RMs / Admins / SuperAdmins) — editing it would
let anyone make themselves a Super Admin — or decide which sheets are read.
These pin that the server enforces it, whatever the screen shows.
"""

import pytest
from sqlalchemy import delete

from app.models.data_source import DataSource
from app.services import jwt_service
from app.services import sheet_admin_service as sa

pytestmark = pytest.mark.asyncio(loop_scope="session")

CSP_SHEET = "csp-sheet-0000000001"
ACCESS_SHEET = "access-sheet-000000001"


def _auth(role: str) -> dict:
    token = jwt_service.create_access_token(
        {"sub": f"{role}.sheets@eko.co.in", "role": role, "name": role})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def sources(db, monkeypatch):
    rows = {
        "records": DataSource(
            name="Test CSP records", kind="google_sheet", purpose="records",
            connection={"spreadsheet_id": CSP_SHEET, "tab": "KOData",
                        "tabs": ["KOData", "SUBKOData"]}, column_map={}),
        "directory": DataSource(
            name="Test INFO", kind="google_sheet", purpose="directory",
            connection={"spreadsheet_id": CSP_SHEET, "tab": "INFO"},
            column_map={}),
        "access": DataSource(
            name="Test access", kind="google_sheet", purpose="authorization",
            connection={"spreadsheet_id": ACCESS_SHEET,
                        "tabs": ["RMs", "Admins"]}, column_map={}),
    }
    for row in rows.values():
        db.add(row)
    await db.commit()

    # Google is not called: each service answers from here.
    calls = []
    monkeypatch.setattr(sa, "describe", lambda sid: {
        "title": sid, "tabs": [{"title": t, "tab_id": n} for n, t in enumerate(
            ["KOData", "SUBKOData", "INFO", "Scratch"] if sid == CSP_SHEET
            else ["RMs", "Admins", "SuperAdmins"])]})
    monkeypatch.setattr(sa, "read_tab", lambda sid, tab: calls.append(
        ("read", sid, tab)) or {"columns": [], "rows": []})
    monkeypatch.setattr(sa, "update_row", lambda sid, tab, n, cells: calls.append(
        ("update", sid, tab)) or (list(cells), []))
    monkeypatch.setattr(sa, "append_row", lambda sid, tab, cells: calls.append(
        ("add", sid, tab)) or (9, []))
    monkeypatch.setattr(sa, "delete_row", lambda sid, tab, n: calls.append(
        ("delete", sid, tab)) or {"CSP Code": "X"})
    yield {k: str(v.id) for k, v in rows.items()}, calls

    await db.execute(delete(DataSource).where(
        DataSource.name.in_([r.name for r in rows.values()])))
    await db.commit()


@pytest.mark.parametrize("role", ["rm", "admin"])
async def test_an_rm_or_admin_is_shown_only_the_csp_tabs(client, sources, role):
    ids, _ = sources
    body = (await client.get("/api/admin/sheets", headers=_auth(role))).json()
    mine = {s["id"]: s for s in body["sheets"] if s["id"] in ids.values()}
    assert ids["access"] not in mine, "the access sheet was listed"
    assert [t["title"] for t in mine[ids["records"]]["tabs_live"]] == ["KOData", "SUBKOData"]
    assert [t["title"] for t in mine[ids["directory"]]["tabs_live"]] == ["INFO"]
    assert all(not s["can_manage"] for s in mine.values())


@pytest.mark.parametrize("role", ["rm", "admin"])
async def test_an_rm_or_admin_can_edit_a_csp_tab(client, sources, role):
    ids, calls = sources
    base = f"/api/admin/sheets/{ids['records']}/tabs/KOData"
    assert (await client.get(base, headers=_auth(role))).status_code == 200
    r = await client.patch(f"{base}/rows/3", headers=_auth(role),
                           json={"cells": {"CSP Name": "Asha"}})
    assert r.status_code == 200, r.text
    r = await client.post(f"{base}/rows", headers=_auth(role),
                          json={"cells": {"CSP Name": "New"}})
    assert r.status_code == 201, r.text
    r = await client.delete(f"{base}/rows/3", headers=_auth(role))
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/admin/sheets/{ids['directory']}/tabs/INFO",
                         headers=_auth(role))
    assert r.status_code == 200
    assert [c[0] for c in calls] == ["read", "update", "add", "delete", "read"]


@pytest.mark.parametrize("role", ["rm", "admin"])
@pytest.mark.parametrize("which, tab", [
    ("access", "RMs"),
    ("access", "SuperAdmins"),        # read without being listed — still refused
    ("records", "Scratch"),           # a tab the system does not read
    ("records", "INFO"),              # a real CSP tab, but not this source's
])
async def test_anything_else_is_refused_and_nothing_reaches_google(
        client, sources, role, which, tab):
    ids, calls = sources
    base = f"/api/admin/sheets/{ids[which]}/tabs/{tab}"
    for method, path, body in (("GET", base, None),
                               ("PATCH", f"{base}/rows/2", {"cells": {"a": "b"}}),
                               ("POST", f"{base}/rows", {"cells": {"a": "b"}}),
                               ("DELETE", f"{base}/rows/2", None)):
        r = await client.request(method, path, headers=_auth(role), json=body)
        assert r.status_code == 403, f"a {role} reached {method} {path}"
    assert calls == [], "a refused request still reached the spreadsheet"


async def test_the_super_admin_still_reaches_the_access_sheet(client, sources):
    ids, calls = sources
    r = await client.get(f"/api/admin/sheets/{ids['access']}/tabs/SuperAdmins",
                         headers=_auth("super_admin"))
    assert r.status_code == 200
    body = (await client.get("/api/admin/sheets", headers=_auth("super_admin"))).json()
    assert ids["access"] in {s["id"] for s in body["sheets"]}
