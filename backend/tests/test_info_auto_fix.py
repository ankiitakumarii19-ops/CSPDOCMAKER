"""The app corrects INFO's AO / RBO itself (No. 153).

Only the corrected branches move; the other branches of a row are not
touched; anything unsafe is left for a person with the reason. The sheet is
a stand-in.
"""

import copy
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.models.csp_record import CSPRecord
from app.models.feedback_loop import QualitySuggestion
from app.services import feedback_loops as fl
from app.services import field_quality as fq
from app.services import info_writer as iw
from app.services.info_directory import InfoDirectory
from tests.test_field_quality import _engine, qdb  # noqa: F401
from tests.test_info_directory import AO_ROWS

HEADER = next(i for i, r in enumerate(AO_ROWS) if r and r[0] == "LHO" and "AO" in r)


def _apply(rows, ops):
    """What the sheet would hold after apply() — to check with the reader."""
    rows = copy.deepcopy(rows)
    for o in ops:
        if o["op"] == "set":
            row = rows[o["row"] - 1]
            row += [""] * (o["col"] + 1 - len(row))
            row[o["col"]] = o["after"]
    for o in sorted((o for o in ops if o["op"] == "insert"),
                    key=lambda o: -o["after_row"]):
        rows.insert(o["after_row"], list(o["values"]))
    return rows


def test_one_branch_moves_and_its_row_neighbour_stays():
    """JAMUI shares a row with GOPALPUR, CHAKAI BAZAR and LAXMIPUR."""
    ops = iw.plan(AO_ROWS, "ao", "AO BHAGALPUR", "AO MUNGER",
                  [{"branch": "GOPALPUR", "state": "Bihar", "district": "Jamui"}])
    after = InfoDirectory.from_rows(_apply(AO_ROWS, ops))
    assert after.find_ao("GOPALPUR", "Jamui", "Bihar") == "AO MUNGER"
    assert after.find_ao("CHAKAI BAZAR", "Jamui", "Bihar") == "AO BHAGALPUR"
    assert after.find_ao("A NEW BRANCH", "Jamui", "Bihar") == "AO BHAGALPUR",         "the district still maps its unlisted branches"
    assert after.find_rbo("GOPALPUR", "Jamui", "Bihar") == "RBO 2", "RBO kept"
    (edit,) = [o for o in ops if o["op"] == "set"]
    assert "GOPALPUR" not in edit["after"] and "JAMUI" in edit["after"]


def test_an_existing_row_with_the_right_value_is_used():
    """ALAMBAGH (Lucknow West, RBO 2) corrected to Lucknow East — but RBO 2
    must stay, and East's row is RBO 1, so a new row is made."""
    ops = iw.plan(AO_ROWS, "ao", "AO LUCKNOW WEST", "AO LUCKNOW EAST",
                  [{"branch": "ALAMBAGH", "state": "Uttar Pradesh",
                    "district": "Lucknow"}])
    assert [o["op"] for o in ops] == ["set", "insert"]
    after = InfoDirectory.from_rows(_apply(AO_ROWS, ops))
    assert after.find_ao("ALAMBAGH", "Lucknow", "Uttar Pradesh") == "AO LUCKNOW EAST"
    assert after.find_rbo("ALAMBAGH", "Lucknow", "Uttar Pradesh") == "RBO 2"

    rows = copy.deepcopy(AO_ROWS) + [["Lucknow", "z@sbi.co.in", "Uttar Pradesh",
                                      "AO LUCKNOW EAST", "", "Lucknow", "RBO 2",
                                      "2", "", "HAZRATGANJ"]]
    ops = iw.plan(rows, "ao", "AO LUCKNOW WEST", "AO LUCKNOW EAST",
                  [{"branch": "ALAMBAGH", "state": "Uttar Pradesh",
                    "district": "Lucknow"}])
    assert [o["op"] for o in ops] == ["set", "set"], "joined the existing row"
    assert ops[1]["after"] == "HAZRATGANJ, ALAMBAGH"


def test_an_rbo_fix_keeps_the_ao():
    ops = iw.plan(AO_ROWS, "rbo_name", "RBO 1", "RBO 4",
                  [{"branch": "VISARWADI", "state": "Maharashtra",
                    "district": "Nandurbar"}])
    after = InfoDirectory.from_rows(_apply(AO_ROWS, ops))
    assert after.find_rbo("VISARWADI", "Nandurbar", "Maharashtra") == "RBO 4"
    assert after.find_ao("VISARWADI", "Nandurbar", "Maharashtra") == "AO NASHIK"


def test_a_csp_matched_by_district_gets_its_branch_listed():
    ops = iw.plan(AO_ROWS, "ao", "AO BHAGALPUR", "AO PURNIA",
                  [{"branch": "SINGHESHWAR", "state": "Bihar",
                    "district": "Madhepura"}])
    after = InfoDirectory.from_rows(_apply(AO_ROWS, ops))
    assert after.find_ao("SINGHESHWAR", "Madhepura", "Bihar") == "AO PURNIA"
    assert after.find_ao("MURLIGANJ", "Madhepura", "Bihar") == "AO BHAGALPUR", \
        "the district's other branches are untouched"
    assert after.find_ao("", "Madhepura", "Bihar") == "AO BHAGALPUR"


@pytest.mark.parametrize("field,wrong,csps,reason", [
    ("dc", "X", [{"branch": "JAMUI"}], "only fixes AO and RBO"),
    ("ao", "AO BHAGALPUR", [{"branch": "", "state": "Bihar"}], "no Branch Name"),
    ("ao", "AO SOMEWHERE", [{"branch": "JAMUI", "state": "Bihar",
                             "district": "Jamui"}], "no longer gives"),
])
def test_unsafe_fixes_are_left_for_a_person(field, wrong, csps, reason):
    with pytest.raises(iw.CannotFix, match=reason):
        iw.plan(AO_ROWS, field, wrong, "AO RIGHT", csps)


def test_a_branch_listed_twice_in_a_state_is_left_for_a_person():
    rows = copy.deepcopy(AO_ROWS) + [["Patna", "", "Bihar", "AO GAYA", "",
                                      "Gaya", "Gaya", "5", "", "JAMUI"]]
    with pytest.raises(iw.CannotFix, match="listed on 2 INFO rows"):
        iw.plan(rows, "ao", "AO BHAGALPUR", "AO RIGHT",
                [{"branch": "JAMUI", "state": "Bihar", "district": "Jamui"}])


# ---- automatic, end to end ----------------------------------------------

class FakeSheet:
    CannotFix = iw.CannotFix
    FIELDS = iw.FIELDS

    def __init__(self):
        self.applied = []

    def plan(self, *a):
        return iw.plan(*a)

    def apply(self, sheet_id, tab, ops):
        self.applied.append(ops)
        return [{"cell": "J1", "before": "x", "after": "y"}]


@pytest.fixture
def adb(qdb, monkeypatch):
    from app.services import csp_gsheet_service
    qdb.execute(text("TRUNCATE quality_suggestions RESTART IDENTITY CASCADE"))
    qdb.commit()
    monkeypatch.setattr(csp_gsheet_service, "read_info_sheet", lambda: AO_ROWS)
    return qdb


def _corrected(db, code, branch="GOPALPUR", to="AO MUNGER",
               rule="INFO AO block, by branch 'GOPALPUR'"):
    db.add(CSPRecord(csp_id=code, csp_code=code, name="Csp", branch_name=branch,
                     state="Bihar", district="Jamui", ao=to))
    db.commit()
    known = fq.load(db, [code])
    fq.record_fill(db, code, "ao", "AO BHAGALPUR", "info", rule, known=known)
    db.commit()
    fq.record_check(db, code, {"ao": to}, "csp_form", "CSP")
    db.commit()


SETTINGS = SimpleNamespace(quality_suggest_min_csps=2,
                           google_sheets_csp_sheet_id="sheet",
                           google_sheets_info_tab_name="INFO")


def test_two_matching_corrections_fix_info_by_themselves(adb):
    _corrected(adb, "1A998001")
    _corrected(adb, "1A998002")
    sheet = FakeSheet()
    assert fl.auto_fix_info(adb, SETTINGS, writer=sheet) == {"fixed": 1, "left": 0}
    s = adb.execute(select(QualitySuggestion)).scalar_one()
    assert (s.status, s.decided_by, s.note) == (
        "fixed", "the app (automatic)", "INFO corrected by the app")
    assert s.applied == [{"cell": "J1", "before": "x", "after": "y"}]
    assert len(sheet.applied) == 1
    assert fl.auto_fix_info(adb, SETTINGS, writer=sheet)["fixed"] == 0, "once"


def test_people_who_disagree_leave_it_to_a_person(adb):
    _corrected(adb, "1A998001")
    _corrected(adb, "1A998002")
    _corrected(adb, "1A998003", to="AO PURNIA")
    _corrected(adb, "1A998004", to="AO PURNIA")
    sheet = FakeSheet()
    assert fl.auto_fix_info(adb, SETTINGS, writer=sheet) == {"fixed": 0, "left": 2}
    assert sheet.applied == []
    notes = {s.note for s in adb.execute(select(QualitySuggestion)).scalars()}
    assert all("different values" in n for n in notes)


def test_the_job_only_runs_on_the_server_and_can_be_off(adb, monkeypatch):
    from app.config import get_settings
    from app.workers import info_fix_worker
    s = get_settings()
    monkeypatch.setattr(s, "public_app_url", "http://localhost:3000")
    assert "not the server" in info_fix_worker.run_once(adb)["skipped"]
    monkeypatch.setattr(s, "info_auto_fix_enabled", False)
    assert "off" in info_fix_worker.run_once(adb)["skipped"]
    from app.celery_app import celery_app
    assert "workers.fix_info" in {e["task"] for e in
                                  celery_app.conf.beat_schedule.values()}
