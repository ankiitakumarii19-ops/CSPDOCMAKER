# -*- coding: utf-8 -*-
"""Editing a CSP from the Database page (No. 175): the whole sheet row,
written to the sheet; RMs their own CSPs, Admins any; checked; a sheet
changed since the form opened is not overwritten; every change logged and
shown; the Sheets tab follows the same RM rule."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.models.audit_log import AuditLog
from app.models.csp_record import CSPRecord
from app.services import csp_editor, jwt_service
from app.services import sheet_admin_service as admin

pytestmark = pytest.mark.asyncio(loop_scope="session")

RM = "rm.edit@eko.co.in"
OTHER = "rm.other@eko.co.in"
HEADER = ["CSP Code", "CSP Name", "CSP Mobile Number", "CSP Email Id",
          "District", "Relationship Manager (RM)"]


def _auth(email, role="rm"):
    token = jwt_service.create_access_token({"sub": email, "role": role, "name": "x"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def sheet(db, monkeypatch):
    """One KO row in a fake KOData; writes land in `written`."""
    monkeypatch.setattr(get_settings(), "google_sheets_csp_sheet_id", "sheet-1")
    rows = [list(HEADER),
            ["1A860001", "Kaushar Jahan", "9812345681", "kj@example.com",
             "Ghaziabad", "Rm Edit"]]
    written = []
    monkeypatch.setattr(csp_editor, "_rows", lambda tab: [list(r) for r in rows])

    def update_row(sheet_id, tab, number, cells):
        written.append((tab, number, dict(cells)))
        for col, value in cells.items():
            rows[number - 1][HEADER.index(col)] = value
        return dict(cells), []
    monkeypatch.setattr(admin, "update_row", update_row)
    db.add(CSPRecord(csp_id="1A860001", csp_code="1A860001", name="Kaushar Jahan",
                     mobile="9812345681", email="kj@example.com", district="Ghaziabad",
                     rm_name="Rm Edit", rm_email=RM, rm_resolution="sheet"))
    db.add(CSPRecord(csp_id="1A860002", csp_code="1A860002", name="Someone Else",
                     rm_email=OTHER, rm_resolution="sheet"))
    await db.commit()
    return rows, written


def _seen(rows, *cols):
    return {c: rows[1][HEADER.index(c)] for c in cols}


async def test_the_form_has_every_column_and_the_code_is_locked(client, sheet):
    body = (await client.get("/api/admin/database/1A860001/edit", headers=_auth(RM))).json()
    cols = {c["column"]: c for c in body["columns"]}
    assert list(cols) == HEADER
    assert cols["CSP Code"]["locked"] is True
    assert cols["CSP Mobile Number"]["kind"] == "phone"
    assert cols["CSP Email Id"]["kind"] == "email"
    assert body["row_number"] == 2 and body["level"] == "KO"


async def test_an_rm_saves_their_csp_and_everything_follows(client, db, sheet):
    rows, written = sheet
    seen = _seen(rows, "District", "CSP Email Id")
    r = await client.put("/api/admin/database/1A860001", headers=_auth(RM), json={
        "changes": {"District": "Noida", "CSP Email Id": "new@example.com"},
        "seen": seen})
    assert r.status_code == 200, r.text
    assert written == [("KOData", 2, {"District": "Noida",
                                      "CSP Email Id": "new@example.com"})]
    db.expire_all()
    record = (await db.execute(select(CSPRecord).where(
        CSPRecord.csp_id == "1A860001"))).scalars().one()
    assert (record.district, record.email) == ("Noida", "new@example.com"), \
        "the portal matches the sheet at once"
    logs = (await db.execute(select(AuditLog).where(
        AuditLog.action == "csp_edit"))).scalars().all()
    assert {(l.metadata_json["column"], l.metadata_json["old"], l.metadata_json["new"],
             l.metadata_json["by"]) for l in logs} == {
        ("District", "Ghaziabad", "Noida", RM),
        ("CSP Email Id", "kj@example.com", "new@example.com", RM)}
    record_view = (await client.get("/api/admin/database/1A860001",
                                    headers=_auth(RM))).json()
    assert record_view["can_edit"] is True
    assert len(record_view["edit_history"]) == 2


async def test_the_rm_name_can_be_changed(client, sheet):
    rows, written = sheet
    r = await client.put("/api/admin/database/1A860001", headers=_auth(RM), json={
        "changes": {"Relationship Manager (RM)": "Vandana"},
        "seen": _seen(rows, "Relationship Manager (RM)")})
    assert r.status_code == 200, r.text


async def test_another_rms_csp_cannot_be_edited_but_admins_can(client, sheet):
    rows, _ = sheet
    r = await client.get("/api/admin/database/1A860002/edit", headers=_auth(RM))
    assert r.status_code == 403
    view = (await client.get("/api/admin/database/1A860002", headers=_auth(RM))).json()
    assert view["can_edit"] is False
    r = await client.put("/api/admin/database/1A860001", headers=_auth("boss@eko.co.in", "admin"),
                         json={"changes": {"District": "Meerut"},
                               "seen": _seen(rows, "District")})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("column,value,says", [
    ("CSP Email Id", "not-an-email", "email"),
    ("CSP Mobile Number", "12345", "mobile"),
    ("CSP Name", "  ", "blank"),
])
async def test_bad_values_are_refused_with_the_reason(client, sheet, column, value, says):
    rows, written = sheet
    r = await client.put("/api/admin/database/1A860001", headers=_auth(RM), json={
        "changes": {column: value}, "seen": _seen(rows, column)})
    assert r.status_code == 400
    assert says in r.json()["detail"]["problems"][column].lower()
    assert written == [], "nothing written"


async def test_two_numbers_in_the_mobile_cell_are_fine(client, sheet):
    rows, _ = sheet
    r = await client.put("/api/admin/database/1A860001", headers=_auth(RM), json={
        "changes": {"CSP Mobile Number": "9812345681 / 9812345682"},
        "seen": _seen(rows, "CSP Mobile Number")})
    assert r.status_code == 200, r.text


async def test_a_sheet_changed_since_the_form_opened_is_not_overwritten(client, sheet):
    rows, written = sheet
    r = await client.put("/api/admin/database/1A860001", headers=_auth(RM), json={
        "changes": {"District": "Noida"}, "seen": {"District": "Somewhere else"}})
    assert r.status_code == 409
    assert "since you opened it" in r.json()["detail"]["problems"]["District"]
    assert written == []


async def test_the_code_cannot_be_changed(client, sheet):
    rows, written = sheet
    r = await client.put("/api/admin/database/1A860001", headers=_auth(RM), json={
        "changes": {"CSP Code": "1A999999"}, "seen": _seen(rows, "CSP Code")})
    assert r.status_code == 400 and written == []


# ---- the Sheets tab follows the same rule -------------------------------------

async def test_the_sheets_tab_refuses_another_rms_row(db, sheet, monkeypatch):
    from types import SimpleNamespace

    from app.routers import sheet_router

    source = SimpleNamespace(connection={"spreadsheet_id": "sheet-1"})
    monkeypatch.setattr(sheet_router.sheets, "read_row", lambda s, t, n: {
        "CSP Code": "1A860002", "CSP Name": "Someone Else"})
    with pytest.raises(HTTPException) as e:
        await sheet_router._check_row_owner(db, {"sub": RM, "role": "rm"},
                                            source, "KOData", 3)
    assert e.value.status_code == 403
    # Their own row, and any row for an Admin, pass.
    monkeypatch.setattr(sheet_router.sheets, "read_row", lambda s, t, n: {
        "CSP Code": "1A860001"})
    assert await sheet_router._check_row_owner(db, {"sub": RM, "role": "rm"},
                                               source, "KOData", 2)
    monkeypatch.setattr(sheet_router.sheets, "read_row", lambda s, t, n: {
        "CSP Code": "1A860002"})
    assert await sheet_router._check_row_owner(db, {"sub": "a@eko.co.in", "role": "admin"},
                                               source, "KOData", 3)
