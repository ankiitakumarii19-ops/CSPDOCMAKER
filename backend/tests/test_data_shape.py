"""Each workspace's own data shape and words (No. 211, Stage 4).

Columns named differently, record types, words, who fills what — each a
workspace's own choice, and Eko's rules unchanged when nothing is set.
"""

import uuid

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.services import (csp_mapping, data_shape, field_ownership,
                          jwt_service, ko_level, sheet_admin_service,
                          workspace_service, workspace_settings)
from app.workspace_context import all_workspaces, workspace

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWNER = "shape.owner@eko.co.in"
EKO = uuid.UUID("00000000-0000-4000-8000-000000000001")
SHEET = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"


@pytest.fixture
async def ws(migrated_db):
    from app.database import async_session_factory
    async with async_session_factory() as s:
        created = await workspace_service.create_workspace(
            s, f"Shape Test {uuid.uuid4().hex[:6]}", OWNER, "Shape Owner")
        await s.commit()
        yield created
        with all_workspaces():
            await s.execute(text("DELETE FROM workspaces WHERE id = :w")
                            .bindparams(w=created.id))
            await s.commit()
    workspace_settings.forget()


def _h(ws):
    return {"Authorization": "Bearer " + jwt_service.create_access_token({
        "sub": OWNER, "email": OWNER, "role": "super_admin",
        "name": "Owner", "ws": str(ws.id)})}


def test_ekos_rules_are_unchanged_when_nothing_is_set():
    with workspace(EKO):
        assert ko_level.level_of("1A850344") == ko_level.KO
        assert ko_level.level_of("1A8503447") == ko_level.SUB_KO
        assert ko_level.level_of("1A85034408") == ko_level.SUB_KO
        assert ko_level.level_of("1A85") is None
        assert ko_level.label_for("1A8503447") == "Sub-KO"
        assert ko_level.parent_ko_code("1A8503447") == "1A850344"
        assert field_ownership.asked_once() == ("ao", "rbo_name")
        assert csp_mapping.map_sheet_row({"CSP Code": "1A850344",
                                          "CSP Mobile Number": "9812300001"}) == {
            "csp_code": "1A850344", "mobile": "9812300001"}


async def test_own_column_names_are_read_in_that_workspace_only(strict_client, ws,
                                                                monkeypatch):
    await strict_client.put("/api/admin/connections/google_sheets_csp_sheet_id",
                            json={"value": SHEET}, headers=_h(ws))
    monkeypatch.setattr(sheet_admin_service, "_header", lambda sid, tab: [
        "Agent Code", "Full Name", "Phone", "Email ID", "Remarks"])
    r = await strict_client.post("/api/admin/columns/guess", headers=_h(ws))
    assert r.status_code == 200, r.text
    g = r.json()["guess"]
    assert g["csp_code"]["header"] == "Agent Code"
    assert g["mobile"]["header"] == "Phone"
    assert "Remarks" not in {v["header"] for v in g.values()}
    r = await strict_client.put("/api/admin/columns", headers=_h(ws), json={
        "columns": {f: v["header"] for f, v in g.items()}})
    assert r.status_code == 200, r.text
    row = {"Agent Code": "ZZ123", "Phone": "9812300002", "Remarks": "x"}
    with workspace(ws.id):
        assert csp_mapping.map_sheet_row(row) == {"csp_code": "ZZ123",
                                                  "mobile": "9812300002"}
        assert csp_mapping.field_for_header("phone ") == "mobile"
        assert csp_mapping.header_for("mobile") == "Phone"
    with workspace(EKO):
        assert csp_mapping.map_sheet_row(row) == {}
        assert csp_mapping.header_for("mobile") == "CSP Mobile Number"


async def test_one_heading_cannot_be_two_fields(strict_client, ws):
    r = await strict_client.put("/api/admin/columns", headers=_h(ws), json={
        "columns": {"mobile": "Phone", "branch_contact": "Phone"}})
    assert r.status_code == 400 and "both" in r.json()["detail"]


async def test_own_record_types_and_words(strict_client, ws):
    h = _h(ws)
    for key, value in (("record_main_lengths", "6"),
                       ("record_second_lengths", "7"),
                       ("word_main_type", "Outlet"),
                       ("word_second_type", "Sub-outlet")):
        r = await strict_client.put(f"/api/admin/settings/{key}",
                                    json={"value": value}, headers=h)
        assert r.status_code == 200, (key, r.text)
    with workspace(ws.id):
        assert ko_level.level_of("AB1234") == ko_level.KO
        assert ko_level.label_for("AB12345") == "Sub-outlet"
        assert ko_level.parent_ko_code("AB12345") == "AB1234"
        assert ko_level.level_of("1A850344") is None
    with workspace(EKO):
        assert ko_level.label_for("1A8503447") == "Sub-KO"
    r = await strict_client.put("/api/admin/settings/record_second_lengths",
                                json={"value": "6"}, headers=h)
    assert r.status_code == 400 and "both types" in r.json()["detail"]
    r = await strict_client.put("/api/admin/settings/record_type_rule",
                                json={"value": "one_type"}, headers=h)
    assert r.status_code == 200
    with workspace(ws.id):
        assert ko_level.level_of("ANY-CODE") == ko_level.KO


async def test_who_fills_what_is_the_workspaces_own(strict_client, ws):
    r = await strict_client.put("/api/admin/settings/asked_once_fields",
                                json={"value": "ao"}, headers=_h(ws))
    assert r.status_code == 200, r.text
    with workspace(ws.id):
        assert field_ownership.asked_once() == ("ao",)
    r = await strict_client.put("/api/admin/settings/asked_once_fields",
                                json={"value": "ao, password"}, headers=_h(ws))
    assert r.status_code == 400 and "'password' is not one of" in r.json()["detail"]
