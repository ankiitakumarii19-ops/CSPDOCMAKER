"""Where auto-filled values came from, and what people did with them (No. 146).

The sheet, Zoho and the Google API are stand-ins; the database is real.
Covers: the reason INFO gives for each value; the sync recording INFO's
fills and noticing sheet edits (correction, confirmation, withdrawal, an
INFO change that is not a correction); the CSP's form and the app's sheet
editor recording checks; Zoho and Address-tab fills; the scoreboard; the
freshness badges; and the endpoints with their roles.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.field_provenance import FieldCorrection, FieldProvenance
from app.models.sync_run import SyncRun
from app.services import field_quality as fq
from app.services.info_directory import InfoDirectory
from app.workspace_context import workspace
from tests.conftest import DEFAULT_WORKSPACE_ID
from tests.test_csp_sync import mock_sheet, run_sync, sheet_row  # noqa: F401
from tests.test_info_directory import AO_ROWS

on_loop = pytest.mark.asyncio(loop_scope="session")

TABLES = ("field_corrections, field_provenance, data_requests, sync_runs, "
          "csp_records, authorization_records")


@pytest.fixture(scope="module")
def _engine(migrated_db):
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    yield engine
    engine.dispose()


@pytest.fixture
def qdb(_engine):
    with Session(_engine) as session:
        session.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        session.commit()
        with workspace(DEFAULT_WORKSPACE_ID):
            yield session
        session.rollback()


@pytest.fixture
def info(monkeypatch):
    """INFO as the sync reads it; a test may swap the rows."""
    state = {"rows": AO_ROWS}
    monkeypatch.setattr(InfoDirectory, "load", classmethod(
        lambda cls: InfoDirectory.from_rows(state["rows"])))
    return state


def _provenance(db, csp_id, field):
    db.expire_all()
    return db.execute(select(FieldProvenance).where(
        FieldProvenance.csp_id == csp_id,
        FieldProvenance.field == field)).scalar_one_or_none()


def _corrections(db, csp_id=None):
    db.expire_all()
    query = select(FieldCorrection).order_by(FieldCorrection.created_at)
    if csp_id:
        query = query.where(FieldCorrection.csp_id == csp_id)
    return db.execute(query).scalars().all()


VISARWADI = {"CSP Code": "1A990001", "CSP Name": "Test Csp",
             "Branch Name": "VISARWADI", "District": "Nandurbar",
             "State": "Maharashtra"}


# ---- the measure --------------------------------------------------------

def test_edit_distance():
    assert fq.levenshtein("", "") == 0
    assert fq.levenshtein("AO NASHIK", "AO NASHIK") == 0
    assert fq.levenshtein("kitten", "sitting") == 3
    assert fq.levenshtein("", "abc") == 3
    assert fq.levenshtein("RBO 4", "RBO 14") == 1


def test_values_are_compared_as_the_sheet_shows_them():
    assert fq.norm("  AO   NASHIK ") == "AO NASHIK"
    assert fq.norm(None) == ""


# ---- INFO says why ------------------------------------------------------

def test_info_says_which_branch_or_district_decided():
    directory = InfoDirectory.from_rows(AO_ROWS)
    why = {}
    filled = directory.fill_missing(
        {"branch_name": "VISARWADI", "district": "Nandurbar",
         "state": "Maharashtra"}, why=why)
    assert filled["ao"] == "AO NASHIK"
    assert why["ao"] == "INFO AO block, by branch 'VISARWADI'"
    assert set(why) == set(filled), "every filled value has a reason"

    why = {}
    directory.fill_missing({"district": "Madhepura", "state": "Bihar"},
                           why=why)
    assert why["ao"] == "INFO AO block, by district 'Madhepura'"


def test_info_names_the_territory_and_the_district():
    from tests.test_info_directory import INFO_ROWS
    directory = InfoDirectory.from_rows(INFO_ROWS)
    why = {}
    filled = directory.fill_missing(
        {"district": "Patna", "lho": "", "state": ""}, why=why)
    assert filled["dc"] == "Ashutosh Pathak"
    assert why["dc"] == "INFO DC block, by district 'Patna'"
    assert why["lho"].startswith("INFO DC block: district 'Patna'")
    assert why["asm_name"] == "INFO ASM block, by LHO 'Patna' and State 'Bihar'"


def test_fill_missing_without_why_is_unchanged():
    directory = InfoDirectory.from_rows(AO_ROWS)
    assert directory.fill_missing({"branch_name": "VISARWADI"})["ao"] \
        == "AO NASHIK"


# ---- the sync -----------------------------------------------------------

def test_the_sync_records_what_info_filled_once(qdb, info, mock_sheet):
    mock_sheet([sheet_row(**VISARWADI)])
    run_sync()
    run_sync()

    p = _provenance(qdb, "1A990001", "ao")
    assert (p.source, p.status, p.auto_value, p.current_value) == (
        "info", "auto", "AO NASHIK", "AO NASHIK")
    assert p.detail == "INFO AO block, by branch 'VISARWADI'"
    assert qdb.execute(select(FieldProvenance).where(
        FieldProvenance.field == "ao")).scalars().all() == [p], \
        "a second run does not add a second row"
    assert _corrections(qdb) == []


def test_a_different_value_typed_in_the_sheet_is_a_correction(
        qdb, info, mock_sheet):
    mock_sheet([sheet_row(**VISARWADI)])
    run_sync()
    mock_sheet([sheet_row(**VISARWADI, AO="AO NASIK ROAD")])
    result = run_sync()
    assert result["sheet_corrections_found"] == 1
    run_sync()      # seen once, counted once

    p = _provenance(qdb, "1A990001", "ao")
    assert (p.status, p.current_value, p.checked_via) == (
        "corrected", "AO NASIK ROAD", "sheet")
    fixes = _corrections(qdb)
    assert len(fixes) == 1
    fix = fixes[0]
    assert (fix.old_value, fix.new_value, fix.changed_via, fix.changed_by) \
        == ("AO NASHIK", "AO NASIK ROAD", "sheet", None)
    assert fix.edit_distance == fq.levenshtein("AO NASHIK", "AO NASIK ROAD")
    assert p.edit_distance == fix.edit_distance
    record = qdb.execute(select(CSPRecord)).scalar_one()
    assert record.ao == "AO NASIK ROAD", "the sheet still wins"


def test_the_same_value_typed_in_the_sheet_confirms_it(qdb, info, mock_sheet):
    mock_sheet([sheet_row(**VISARWADI)])
    run_sync()
    mock_sheet([sheet_row(**VISARWADI, AO="AO  NASHIK")])
    assert run_sync()["sheet_corrections_found"] == 0
    p = _provenance(qdb, "1A990001", "ao")
    assert (p.status, p.checked_via) == ("confirmed", "sheet")
    assert _corrections(qdb) == []


def test_a_guess_info_stops_making_is_withdrawn_not_corrected(
        qdb, info, mock_sheet):
    mock_sheet([sheet_row(**VISARWADI)])
    run_sync()
    mock_sheet([sheet_row(**{**VISARWADI, "Branch Name": "",
                             "District": "Nowhere"})])
    run_sync()
    assert _provenance(qdb, "1A990001", "ao").status == "withdrawn"
    assert _corrections(qdb) == []
    assert "ao" not in fq.sources_for(qdb, "1A990001")


def test_info_changing_its_answer_is_a_new_fill_not_a_correction(
        qdb, info, mock_sheet):
    mock_sheet([sheet_row(**VISARWADI)])
    run_sync()
    info["rows"] = [[c.replace("AO NASHIK", "AO DHULE") if isinstance(c, str)
                     else c for c in row] for row in AO_ROWS]
    run_sync()
    p = _provenance(qdb, "1A990001", "ao")
    assert (p.status, p.auto_value, p.current_value) == (
        "auto", "AO DHULE", "AO DHULE")
    assert _corrections(qdb) == []


def test_a_broken_measurement_never_stops_the_sync(
        qdb, info, mock_sheet, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("provenance table unavailable")
    monkeypatch.setattr(fq, "observe_sync", broken)
    mock_sheet([sheet_row(**VISARWADI)])
    result = run_sync()
    assert result["status"] == "completed"
    assert result["quality_errors"] == 1
    assert qdb.execute(select(CSPRecord)).scalar_one().ao == "AO NASHIK"


# ---- people checking ----------------------------------------------------

def _filled(db, csp_id="1A990002", **fields):
    known = fq.load(db, [csp_id])
    for field, (value, source) in fields.items():
        fq.record_fill(db, csp_id, field, value, source, f"test {source}",
                       known=known)
    db.commit()


def test_a_check_confirms_or_corrects_and_ignores_the_rest(qdb):
    _filled(qdb, ao=("AO NASHIK", "info"), address=("Ward 4, Gaya", "zoho"))
    counts = fq.record_check(qdb, "1A990002", {
        "ao": "AO NASHIK", "address": "Ward 4, Gaya 823001", "gender": "Male",
    }, "csp_form", "CSP")
    qdb.commit()
    assert counts == {"confirmed": 1, "corrected": 1}
    assert _provenance(qdb, "1A990002", "ao").status == "confirmed"
    p = _provenance(qdb, "1A990002", "address")
    assert (p.status, p.checked_via, p.checked_by) == (
        "corrected", "csp_form", "CSP")
    assert _provenance(qdb, "1A990002", "gender") is None
    assert [c.changed_via for c in _corrections(qdb)] == ["csp_form"]


def test_a_blank_answer_is_no_opinion(qdb):
    _filled(qdb, ao=("AO NASHIK", "info"))
    assert fq.record_check(qdb, "1A990002", {"ao": "  "}, "csp_form",
                           "CSP") == {"confirmed": 0, "corrected": 0}
    assert _provenance(qdb, "1A990002", "ao").status == "auto"


def test_a_whole_row_sent_back_unchanged_confirms_nothing(qdb):
    _filled(qdb, address=("Ward 4, Gaya", "zoho"))
    counts = fq.record_check(qdb, "1A990002", {"address": "Ward 4, Gaya"},
                             "sheet_editor", "admin@eko.co.in", False)
    assert counts == {"confirmed": 0, "corrected": 0}
    assert _provenance(qdb, "1A990002", "address").status == "auto"


def test_the_sync_does_not_count_a_form_answer_twice(qdb):
    _filled(qdb, address=("Ward 4, Gaya", "zoho"))
    fq.record_check(qdb, "1A990002", {"address": "Ward 5, Gaya"},
                    "csp_form", "CSP")
    qdb.commit()
    known = fq.load(qdb)
    assert fq.observe_sync(qdb, known, "1A990002",
                           {"address": "Ward 5, Gaya"}, {}) == 0
    assert len(_corrections(qdb)) == 1


def test_a_correction_put_back_is_confirmed(qdb):
    _filled(qdb, ao=("AO NASHIK", "info"))
    fq.record_check(qdb, "1A990002", {"ao": "AO PUNE"}, "csp_form", "CSP")
    fq.record_check(qdb, "1A990002", {"ao": "AO NASHIK"}, "sheet_editor",
                    "admin@eko.co.in", False)
    qdb.commit()
    p = _provenance(qdb, "1A990002", "ao")
    assert (p.status, p.edit_distance) == ("confirmed", None)
    assert [c.edit_distance for c in _corrections(qdb)] == [
        fq.levenshtein("AO NASHIK", "AO PUNE"), 0]


@on_loop
async def test_the_csp_form_records_what_they_kept_and_changed(
        client, qdb, monkeypatch):
    from app.services import data_request_service as drs
    from app.services import sheet_writeback_service as wb

    qdb.add(CSPRecord(csp_id="1A990003", csp_code="1A990003", name="Form Csp",
                      ao="AO NASHIK", address="Ward 4, Gaya",
                      gender="Male", mobile="9800000003"))
    qdb.flush()
    _filled(qdb, "1A990003", ao=("AO NASHIK", "info"),
            address=("Ward 4, Gaya", "zoho"))
    request, token = drs.create(qdb, "1A990003", ["ao", "address", "gender"])
    qdb.commit()
    monkeypatch.setattr(wb, "write_values",
                        lambda code, values, **k: (dict(values), []))

    r = await client.post(f"/api/csp-form/{token}", json={"values": {
        "ao": "AO NASHIK", "address": "Ward 4, Gaya 823001",
        "gender": "Female"}})
    assert r.status_code == 200, r.text

    ao = _provenance(qdb, "1A990003", "ao")
    assert (ao.status, ao.checked_via, ao.checked_by) == (
        "confirmed", "csp_form", "CSP")
    address = _provenance(qdb, "1A990003", "address")
    assert (address.status, address.current_value) == (
        "corrected", "Ward 4, Gaya 823001")
    fixes = _corrections(qdb, "1A990003")
    assert [(c.field, c.changed_via) for c in fixes] == [
        ("address", "csp_form")]


@on_loop
async def test_the_form_still_succeeds_if_nothing_can_be_recorded(
        client, qdb, monkeypatch):
    from app.services import data_request_service as drs
    from app.services import sheet_writeback_service as wb

    qdb.add(CSPRecord(csp_id="1A990004", csp_code="1A990004", name="Csp",
                      gender="Male", mobile="9800000004"))
    qdb.flush()
    request, token = drs.create(qdb, "1A990004", ["gender"])
    qdb.commit()
    monkeypatch.setattr(wb, "write_values",
                        lambda code, values, **k: (dict(values), []))

    def broken(*a, **k):
        raise RuntimeError("provenance table unavailable")
    monkeypatch.setattr(fq, "record_check", broken)
    r = await client.post(f"/api/csp-form/{token}",
                          json={"values": {"gender": "Female"}})
    assert r.status_code == 200, r.text
    assert r.json()["received"] == ["gender"]


@on_loop
async def test_the_sheet_editor_names_who_corrected_it(qdb, monkeypatch):
    from app.database import async_session_factory
    from app.routers import sheet_router
    from app.services import sheet_admin_service

    _filled(qdb, "1A990005", ao=("AO NASHIK", "info"),
            address=("Ward 4, Gaya", "zoho"))
    monkeypatch.setattr(sheet_admin_service, "read_row",
                        lambda *a: {"CSP Code": "1A990005"})
    s = get_settings()
    async with async_session_factory() as session:
        await sheet_router._note_corrections(
            session, {"sub": "admin.one@eko.co.in"},
            s.google_sheets_csp_sheet_id, s.google_sheets_csp_sheet_name, 7,
            {"AO": "AO DHULE", "Address": "Ward 4, Gaya", "CSP Name": "X"})

    ao = _provenance(qdb, "1A990005", "ao")
    assert (ao.status, ao.checked_via, ao.checked_by) == (
        "corrected", "sheet_editor", "admin.one@eko.co.in")
    assert _provenance(qdb, "1A990005", "address").status == "auto", \
        "an unchanged cell in the row is not a confirmation"


@on_loop
async def test_the_sheet_editor_ignores_other_tabs(qdb, monkeypatch):
    from app.database import async_session_factory
    from app.routers import sheet_router
    from app.services import sheet_admin_service

    _filled(qdb, "1A990005", ao=("AO NASHIK", "info"))
    calls = []
    monkeypatch.setattr(sheet_admin_service, "read_row",
                        lambda *a: calls.append(a) or {})
    async with async_session_factory() as session:
        await sheet_router._note_corrections(
            session, {"sub": "a@eko.co.in"}, get_settings()
            .google_sheets_csp_sheet_id, "INFO", 3, {"AO": "AO DHULE"})
    assert calls == []
    assert _provenance(qdb, "1A990005", "ao").status == "auto"


# ---- Zoho and the Address tab ------------------------------------------

def test_zoho_fills_are_recorded_with_the_lead(qdb, monkeypatch):
    from app.services import sheet_writeback_service as wb
    from app.services import zoho_client, zoho_fill

    lead = {"id": "L77", "Email": "csp@example.com",
            "Shop_Address_with_Shop_Name": "Shop 1, Main Road, 823001",
            "States": "", "Gender": ""}
    monkeypatch.setattr(zoho_client, "is_configured", lambda: True)
    monkeypatch.setattr(zoho_client, "find_lead", lambda *a, **k: lead)
    monkeypatch.setattr(wb, "write_values",
                        lambda code, values, *a, **k: (dict(values), []))
    monkeypatch.setattr(zoho_fill, "_is_eko", lambda session: True)
    record = CSPRecord(csp_id="1A990006", name="Csp", mobile="9800000006",
                       branch_code="1234", state="Bihar", gender="Male")
    qdb.add(record)
    qdb.commit()

    filled = zoho_fill.fill_from_zoho(qdb, record)
    qdb.commit()
    assert set(filled) == {"email", "address"}
    p = _provenance(qdb, "1A990006", "email")
    assert (p.source, p.detail, p.auto_value) == (
        "zoho", "Zoho Lead L77: Email", "csp@example.com")
    assert _provenance(qdb, "1A990006", "address").source == "zoho"


def test_address_tab_fills_are_recorded(qdb):
    from app.services import source_sheets
    source_sheets._record_fills(qdb, {"1A990007": "House 9, Patna"},
                                "address_tab", "Address tab (Address)")
    qdb.commit()
    p = _provenance(qdb, "1A990007", "address")
    assert (p.source, p.auto_value, p.status) == (
        "address_tab", "House 9, Patna", "auto")


def test_rows_copied_into_cspdata_record_their_automatic_cells(qdb):
    from app.services import source_sheets
    states = {"1A990008": SimpleNamespace(zoho_filled={
        "CSP Email Id": "Email", "_lead_id": "L5"}),
        "1A990009": SimpleNamespace(zoho_filled=None)}
    planned = {"1A990008": {"CSP Code": "1A990008",
                            "CSP Email Id": "new@example.com"},
               "1A990009": {"CSP Code": "1A990009", "Address": "Lane 2"}}
    source_sheets._record_import_fills(
        qdb, [("1A990008", "new"), ("1A990009", "baseline")], planned,
        {"1A990009"}, states)
    qdb.commit()
    p = _provenance(qdb, "1A990008", "email")
    assert (p.source, p.detail) == ("zoho", "Zoho Lead L5: Email")
    assert _provenance(qdb, "1A990009", "address").source == "address_tab"


# ---- the scoreboard -----------------------------------------------------

def test_the_scoreboard_counts_and_rates(qdb):
    for n, code in enumerate(["1A991001", "1A991002", "1A991003",
                              "1A991004"]):
        _filled(qdb, code, ao=("AO NASHIK", "info"))
    fq.record_check(qdb, "1A991003", {"ao": "AO NASHIK"}, "csp_form", "CSP")
    fq.record_check(qdb, "1A991004", {"ao": "AO NASIK"}, "csp_form", "CSP")
    qdb.commit()

    board = fq.scoreboard(qdb)
    (row,) = board["fields"]
    assert (row["field"], row["source"], row["filled"], row["auto"],
            row["confirmed"], row["corrected"]) == ("ao", "info", 4, 2, 1, 1)
    assert row["acceptance_rate"] == 75.0
    assert row["checked_kept_rate"] == 50.0
    assert row["avg_edit_distance"] == 1.0
    assert board["total"]["corrected"] == 1
    assert board["total"]["avg_edit_distance"] == 1.0
    (week,) = board["trend"]
    assert (week["filled"], week["corrections"]) == (4, 1)

    listed = fq.recent_corrections(qdb)
    assert listed["total"] == 1
    assert listed["corrections"][0]["changed_via"] == "CSP's own form"


def test_an_empty_scoreboard_has_no_rates(qdb):
    board = fq.scoreboard(qdb)
    assert board["fields"] == [] and board["trend"] == []
    assert board["total"]["acceptance_rate"] is None


# ---- freshness ----------------------------------------------------------

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
SETTINGS = SimpleNamespace(csp_sync_interval_minutes=1,
                           google_sheets_sync_interval_minutes=15,
                           source_sheets_interval_minutes=15,
                           calling_sheet_id="", lead_sheet_id="")


def _run(db, source, status, started_minutes_ago, took=1, error=None):
    started = NOW - timedelta(minutes=started_minutes_ago)
    db.add(SyncRun(source=source, status=status, started_at=started,
                   finished_at=(None if status == "running"
                                else started + timedelta(minutes=took)),
                   error_message=error))


def _badges(db, **kw):
    db.commit()
    return {b["source"]: b for b in fq.freshness(db, SETTINGS, now=NOW, **kw)}


def test_a_recent_read_is_ok_and_none_is_never(qdb):
    _run(qdb, "csp", "completed", 3)
    _run(qdb, "csp", "running", 0)
    badges = _badges(qdb)
    assert badges["csp"]["status"] == "ok"
    assert badges["csp"]["minutes_since_success"] == 2
    assert badges["authorization"]["status"] == "never"
    assert "source_sheets" not in badges, "not configured, never run"
    assert "address" not in badges, "the temporary tab is shown once used"


def test_an_old_read_is_stale(qdb):
    _run(qdb, "csp", "completed", 31)
    assert _badges(qdb)["csp"]["status"] == "stale"


def test_runs_that_never_finish_are_stuck(qdb):
    """22-23 Oct (No. 144): every run started, none finished."""
    _run(qdb, "csp", "completed", 24 * 60)
    for minutes in (120, 60, 30, 1):
        _run(qdb, "csp", "running", minutes)
    badge = _badges(qdb)["csp"]
    assert badge["status"] == "stuck"
    assert badge["unfinished_runs"] == 3


def test_a_failed_read_says_why_to_admins_only(qdb):
    _run(qdb, "csp", "completed", 5)
    _run(qdb, "csp", "failed", 2, error="HttpError 403: no access")
    assert _badges(qdb)["csp"]["status"] == "failed"
    assert "error" not in _badges(qdb)["csp"]
    assert _badges(qdb, with_errors=True)["csp"]["error"] \
        == "HttpError 403: no access"


@on_loop
async def test_the_calling_sheet_job_records_its_runs(qdb, monkeypatch):
    from app.services import source_sheets
    from app.workers import source_sheets_worker

    s = get_settings()
    monkeypatch.setattr(s, "calling_sheet_id", "calling-0001")
    monkeypatch.setattr(s, "lead_sheet_id", "lead-0001")
    monkeypatch.setattr(source_sheets, "run", lambda session:
                        source_sheets.Summary(calling_rows=3, lead_rows=2))
    source_sheets_worker.sync_source_sheets.apply().get()
    qdb.expire_all()
    run = qdb.execute(select(SyncRun).where(
        SyncRun.source == "source_sheets")).scalar_one()
    assert (run.status, run.rows_read) == ("completed", 5)
    assert run.finished_at is not None


# ---- the endpoints ------------------------------------------------------

def _auth(role):
    from tests.test_role_separation import _auth as auth
    return auth(role)


@on_loop
async def test_every_role_sees_freshness_but_only_admins_the_reason(
        client, qdb):
    _run(qdb, "csp", "failed", 0, error="HttpError 500")
    qdb.commit()
    r = await client.get("/api/quality/freshness", headers=_auth("rm"))
    assert r.status_code == 200, r.text
    csp = {b["source"]: b for b in r.json()["sources"]}["csp"]
    assert csp["status"] == "failed" and "error" not in csp
    r = await client.get("/api/quality/freshness", headers=_auth("admin"))
    csp = {b["source"]: b for b in r.json()["sources"]}["csp"]
    assert csp["error"] == "HttpError 500"
    r = await client.get("/api/quality/freshness")
    assert r.status_code in (401, 403)


@on_loop
async def test_the_scoreboard_is_for_admins(client, qdb):
    _filled(qdb, "1A992001", ao=("AO NASHIK", "info"))
    r = await client.get("/api/admin/quality/scoreboard",
                         headers=_auth("rm"))
    assert r.status_code == 403
    r = await client.get("/api/admin/quality/scoreboard",
                         headers=_auth("super_admin"))
    assert r.status_code == 200, r.text
    assert r.json()["fields"][0]["filled"] == 1
    r = await client.get("/api/admin/quality/corrections?limit=5",
                         headers=_auth("admin"))
    assert r.status_code == 200 and r.json()["total"] == 0


@on_loop
async def test_the_csp_panel_says_where_each_value_came_from(client, qdb):
    qdb.add(CSPRecord(csp_id="1A992002", csp_code="1A992002", name="Panel",
                      ao="AO NASHIK"))
    qdb.commit()
    _filled(qdb, "1A992002", ao=("AO NASHIK", "info"))
    r = await client.get("/api/admin/csp/1A992002/summary",
                         headers=_auth("admin"))
    assert r.status_code == 200, r.text
    ao = r.json()["sources"]["ao"]
    assert (ao["source_label"], ao["detail"], ao["status"]) == (
        "INFO tab", "test info", "auto")
