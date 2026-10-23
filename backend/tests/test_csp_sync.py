"""CSP sheet → PostgreSQL sync, and RM resolution.

The Google Sheet is mocked; the database is real. Covers the confirmed rules:
sheet is truth, only changed cells are written, the first sync is a baseline
of existing CSPs, later rows are new CSPs, and every CSP resolves to one RM
or to 'unresolved'.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.authorization_record import AuthorizationRecord
from app.models.csp_record import CSPRecord
from app.models.enums import UserRole
from app.models.sync_run import SyncRun
from app.services import rm_resolution
from app.workers import csp_sync_worker

HEADERS_ROW = {
    "CSP Code": "", "CSP Name": "", "CSP Mobile Number": "", "CSP Email Id": "",
    "Branch Name": "", "Branch Code": "", "Address": "", "District": "",
    "State": "", "AO": "", "DC": "", "LHO": "", "Relationship Manager (RM)": "",
    "ASM": "", "ASM Email Id": "", "ASM Contact Number": "", "RBO Name": "",
    "Photo": "",
}


def sheet_row(**overrides) -> dict:
    row = dict(HEADERS_ROW)
    row.update(overrides)
    return row


@pytest.fixture
def sync_db(migrated_db):
    """Synchronous session against the migrated test database (workers are sync)."""
    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    with Session(engine) as session:
        for table in ("sync_runs", "csp_records", "authorization_records"):
            session.execute(__import__("sqlalchemy").text(
                f"TRUNCATE {table} RESTART IDENTITY CASCADE"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def authorized_rms(sync_db):
    for name, email in (("Rm One", "rm.one@eko.co.in"), ("Rm Two", "rm.two@eko.co.in")):
        sync_db.add(AuthorizationRecord(
            email=email, name=name, mobile="9876543210",
            role=UserRole.RM, active=True, source="google_sheet",
        ))
    sync_db.commit()


@pytest.fixture
def mock_sheet(monkeypatch):
    rows = []

    def set_rows(new_rows):
        rows[:] = new_rows

    monkeypatch.setattr(csp_sync_worker, "__doc__", csp_sync_worker.__doc__)
    import app.services.csp_gsheet_service as gsheet
    monkeypatch.setattr(gsheet, "read_csp_sheet", lambda: list(rows))
    return set_rows


def _only_workspace(outcome):
    """Unwrap a per-workspace task result.

    Every periodic task now runs once per active workspace and returns
    {"workspaces": n, "results": [{"workspace": slug, "result": ...}]}.
    These tests have one workspace and care about the work, not the
    wrapper — but they still go through it, so the wrapper stays covered.
    """
    assert outcome["workspaces"] == 1, outcome
    first = outcome["results"][0]
    assert "error" not in first, first["error"]
    return first["result"]


def run_sync():
    return _only_workspace(
        csp_sync_worker.sync_csp_data.apply().get())


# ---- RM resolution rules (pure logic) ----------------------------------

class _Rec:
    def __init__(self, name, email):
        self.name, self.email = name, email


def test_name_to_email_ignores_case_and_spacing():
    mapping = rm_resolution.build_name_to_email([_Rec("  Rm   One ", "RM.One@eko.co.in")])
    assert mapping[rm_resolution.normalize_name("rm one")] == "rm.one@eko.co.in"


def test_duplicate_rm_names_are_not_resolved():
    mapping = rm_resolution.build_name_to_email([
        _Rec("Rm One", "a@eko.co.in"), _Rec("RM ONE", "b@eko.co.in"),
    ])
    assert mapping == {}


def test_lho_map_is_learned_from_rows_that_name_an_rm():
    rows = [{"lho": "Delhi", "rm_name": "Rm One"}, {"lho": "Delhi", "rm_name": ""}]
    assert rm_resolution.build_lho_to_name(rows) == {"delhi": "rm one"}


def test_conflicting_lho_is_dropped():
    rows = [{"lho": "Delhi", "rm_name": "Rm One"}, {"lho": "Delhi", "rm_name": "Rm Two"}]
    assert rm_resolution.build_lho_to_name(rows) == {}


def test_one_rm_can_own_several_lhos():
    rows = [{"lho": "Delhi", "rm_name": "Rm One"}, {"lho": "Mumbai", "rm_name": "Rm One"}]
    assert rm_resolution.build_lho_to_name(rows) == {"delhi": "rm one", "mumbai": "rm one"}


# ---- Sync behaviour (real database) -------------------------------------

def test_first_sync_is_a_baseline_of_existing_csps(sync_db, authorized_rms, mock_sheet):
    mock_sheet([
        sheet_row(**{"CSP Code": "C1", "CSP Name": "One",
                     "Relationship Manager (RM)": "Rm One", "LHO": "Delhi"}),
        sheet_row(**{"CSP Code": "C2", "CSP Name": "Two",
                     "Relationship Manager (RM)": "Rm Two", "LHO": "Mumbai"}),
    ])
    result = run_sync()
    assert result["baseline"] is True and result["new_csps"] == 0

    records = sync_db.execute(select(CSPRecord)).scalars().all()
    assert {r.csp_id for r in records} == {"C1", "C2"}
    assert all(r.origin == "baseline" for r in records)
    assert all(r.new_csp_processed_at is None for r in records)


def test_rows_added_after_the_baseline_are_new_csps(sync_db, authorized_rms, mock_sheet):
    mock_sheet([sheet_row(**{"CSP Code": "C1", "CSP Name": "One",
                             "Relationship Manager (RM)": "Rm One"})])
    run_sync()
    mock_sheet([
        sheet_row(**{"CSP Code": "C1", "CSP Name": "One",
                     "Relationship Manager (RM)": "Rm One"}),
        sheet_row(**{"CSP Code": "C2", "CSP Name": "Two",
                     "Relationship Manager (RM)": "Rm Two"}),
    ])
    result = run_sync()
    assert result["baseline"] is False and result["new_csps"] == 1

    origins = {r.csp_id: r.origin for r in sync_db.execute(select(CSPRecord)).scalars()}
    assert origins == {"C1": "baseline", "C2": "new"}


def test_only_changed_cells_are_written(sync_db, authorized_rms, mock_sheet):
    mock_sheet([sheet_row(**{"CSP Code": "C1", "CSP Name": "One", "Address": "Old Address",
                             "Relationship Manager (RM)": "Rm One"})])
    run_sync()
    unchanged = run_sync()
    assert unchanged["updated_csps"] == 0, "a no-change sync must not write"

    mock_sheet([sheet_row(**{"CSP Code": "C1", "CSP Name": "One", "Address": "New Address",
                             "Relationship Manager (RM)": "Rm One"})])
    changed = run_sync()
    assert changed["updated_csps"] == 1
    record = sync_db.execute(select(CSPRecord)).scalar_one()
    assert record.address == "New Address"


def test_rm_is_resolved_from_the_rm_column(sync_db, authorized_rms, mock_sheet):
    mock_sheet([sheet_row(**{"CSP Code": "C1", "CSP Name": "One",
                             "Relationship Manager (RM)": "Rm One", "LHO": "Delhi"})])
    run_sync()
    record = sync_db.execute(select(CSPRecord)).scalar_one()
    assert record.rm_email == "rm.one@eko.co.in"
    assert record.rm_resolution == rm_resolution.BY_SHEET


def test_empty_rm_falls_back_to_the_lho_owner(sync_db, authorized_rms, mock_sheet):
    mock_sheet([
        sheet_row(**{"CSP Code": "C1", "CSP Name": "One",
                     "Relationship Manager (RM)": "Rm One", "LHO": "Delhi"}),
        sheet_row(**{"CSP Code": "C2", "CSP Name": "Two",
                     "Relationship Manager (RM)": "", "LHO": "Delhi"}),
    ])
    run_sync()
    records = {r.csp_id: r for r in sync_db.execute(select(CSPRecord)).scalars()}
    assert records["C2"].rm_email == "rm.one@eko.co.in"
    assert records["C2"].rm_resolution == rm_resolution.BY_LHO


def test_unknown_rm_and_unknown_lho_are_unresolved(sync_db, authorized_rms, mock_sheet):
    mock_sheet([
        sheet_row(**{"CSP Code": "C1", "CSP Name": "One",
                     "Relationship Manager (RM)": "Not An Rm"}),
        sheet_row(**{"CSP Code": "C2", "CSP Name": "Two", "LHO": "Unknown Lho"}),
        sheet_row(**{"CSP Code": "C3", "CSP Name": "Three"}),
    ])
    run_sync()
    records = {r.csp_id: r for r in sync_db.execute(select(CSPRecord)).scalars()}
    for csp_id in ("C1", "C2", "C3"):
        assert records[csp_id].rm_email is None
        assert records[csp_id].rm_resolution == rm_resolution.UNRESOLVED


def test_rows_without_a_csp_code_are_skipped(sync_db, authorized_rms, mock_sheet):
    mock_sheet([
        sheet_row(**{"CSP Code": "", "CSP Name": "No Code"}),
        sheet_row(**{"CSP Code": "C1", "CSP Name": "One"}),
    ])
    result = run_sync()
    assert result["skipped_rows"] == 1
    assert sync_db.execute(select(CSPRecord)).scalars().all()[0].csp_id == "C1"


def test_a_mobile_cell_with_two_numbers_is_saved(sync_db, authorized_rms,
                                                 mock_sheet):
    """No. 144: "9905985993/ 7563993807" did not fit the column, and the
    whole sync failed with it."""
    mock_sheet([sheet_row(**{"CSP Code": "C1", "CSP Name": "One",
                             "CSP Mobile Number": "9905985993/ 7563993807"})])
    assert run_sync()["skipped_rows"] == 0
    record = sync_db.execute(select(CSPRecord)).scalars().one()
    assert record.mobile == "9905985993/ 7563993807"


def test_one_row_the_database_refuses_does_not_stop_the_rest(
        sync_db, authorized_rms, mock_sheet):
    mock_sheet([
        sheet_row(**{"CSP Code": "C1", "CSP Name": "One"}),
        sheet_row(**{"CSP Code": "C2", "CSP Name": "Two",
                     "CSP Mobile Number": "9" * 60}),
        sheet_row(**{"CSP Code": "C3", "CSP Name": "Three"}),
    ])
    result = run_sync()

    assert result["skipped_rows"] == 1
    saved = {r.csp_id for r in sync_db.execute(select(CSPRecord)).scalars()}
    assert saved == {"C1", "C3"}
    run = sync_db.execute(select(SyncRun)).scalars().one()
    assert run.status == "completed"
    assert "C2" in run.error_message, "the skipped row is not named"


def test_a_sync_that_cannot_be_saved_is_marked_failed(
        sync_db, authorized_rms, mock_sheet, monkeypatch):
    """Not left "running" with no error, as 1333 runs were on the server."""
    from sqlalchemy.orm import Session as OrmSession
    mock_sheet([sheet_row(**{"CSP Code": "C1", "CSP Name": "One"})])
    real_commit = OrmSession.commit
    calls = {"n": 0}

    def commit_fails_once_at_the_end(self):
        calls["n"] += 1
        if calls["n"] == 2:      # 1: the run row; 2: the sync itself
            raise RuntimeError("database went away")
        return real_commit(self)

    monkeypatch.setattr(OrmSession, "commit", commit_fails_once_at_the_end)
    with pytest.raises(Exception):
        run_sync()
    monkeypatch.setattr(OrmSession, "commit", real_commit)

    sync_db.expire_all()
    runs = sync_db.execute(select(SyncRun)).scalars().all()
    assert runs and runs[0].status == "failed"
    assert "database went away" in runs[0].error_message


def test_a_sheet_failure_is_recorded_and_retried_not_shown(sync_db, monkeypatch):
    import app.services.csp_gsheet_service as gsheet

    def boom():
        raise RuntimeError("Google Sheets API error: HTTP 403 - permission denied")

    monkeypatch.setattr(gsheet, "read_csp_sheet", boom)
    # The task asks Celery to retry; running eagerly in tests surfaces the
    # original error instead of scheduling the retry.
    with pytest.raises(RuntimeError, match="403"):
        run_sync()

    # Each attempt (the first plus its retries) records its own failed run.
    runs = sync_db.execute(select(SyncRun)).scalars().all()
    assert runs and all(r.status == "failed" for r in runs)
    assert all("403" in r.error_message for r in runs)
    # A failed run must not count as the baseline being done.
    assert sync_db.execute(select(CSPRecord)).scalars().all() == []


def test_application_owned_fields_survive_a_sync(sync_db, authorized_rms, mock_sheet):
    """certificate_date and new-CSP bookkeeping are not sheet columns."""
    from datetime import date, datetime, timezone
    mock_sheet([sheet_row(**{"CSP Code": "C1", "CSP Name": "One",
                             "Relationship Manager (RM)": "Rm One"})])
    run_sync()
    record = sync_db.execute(select(CSPRecord)).scalar_one()
    record.certificate_date = date(2026, 3, 4)
    record.new_csp_processed_at = datetime(2026, 3, 4, tzinfo=timezone.utc)
    sync_db.commit()

    run_sync()
    sync_db.expire_all()
    record = sync_db.execute(select(CSPRecord)).scalar_one()
    assert record.certificate_date == date(2026, 3, 4)
    assert record.new_csp_processed_at is not None
