# -*- coding: utf-8 -*-
"""Writing a correction back to the CSP sheet.

The sheet is read every minute and treated as truth, so a correction that
does not reach it is undone by the next sync. That makes write-back
necessary — and makes writing to the WRONG row the thing to guard against,
because it puts one CSP's details onto another's record.
"""

import pytest

from app.services import sheet_writeback_service as w

pytestmark = pytest.mark.asyncio(loop_scope="session")

HEADER = ["CSP Code", "CSP Name", "CSP Mobile Number", "CSP Email Id",
          "Gender", "Address", "District", "State"]
ROWS = [
    HEADER,
    ["1A850466", "Abhishek Anand", "9812345671", "a@x.com", "Male",
     "Saharsa", "Saharsa", "Bihar"],
    ["1A851727", "Nitasha", "9812345670", "", "", "", "", ""],
]


# ---- locating the right cell -------------------------------------------

@pytest.mark.parametrize("index,letter", [
    (0, "A"), (1, "B"), (22, "W"), (25, "Z"), (26, "AA"), (51, "AZ"),
])
async def test_column_letters(index, letter):
    assert w.column_letter(index) == letter


async def test_columns_are_found_by_their_header_not_their_position():
    """Moving a column in the sheet must not corrupt the next write."""
    moved = ["CSP Name", "CSP Code", "Gender"]
    columns = w.find_columns(moved)
    assert columns["csp_code"] == 1
    assert columns["name"] == 0


async def test_header_matching_ignores_case_and_spacing():
    columns = w.find_columns(["  csp   code ", "CSP NAME"])
    assert columns["csp_code"] == 0
    assert columns["name"] == 1


async def test_an_unknown_header_is_ignored():
    columns = w.find_columns(["CSP Code", "Some Column Nobody Mapped"])
    assert list(columns) == ["csp_code"]


# ---- never the wrong row -----------------------------------------------

async def test_the_row_is_found_by_csp_code():
    assert w.find_row(ROWS, 0, "1A851727") == 3


async def test_matching_a_code_ignores_case_and_spacing():
    assert w.find_row(ROWS, 0, "  1a850466 ") == 2


async def test_a_duplicated_code_stops_the_write():
    """Two rows claiming one CSP: writing to either could be wrong."""
    rows = ROWS + [["1A850466", "Someone Else", "", "", "", "", "", ""]]
    with pytest.raises(w.SheetWriteError, match="appears on rows"):
        w.find_row(rows, 0, "1A850466")


async def test_a_code_that_is_not_there_stops_the_write():
    with pytest.raises(w.SheetWriteError, match="not in the sheet"):
        w.find_row(ROWS, 0, "1A999999")


async def test_no_code_at_all_stops_the_write():
    with pytest.raises(w.SheetWriteError, match="without a CSP Code"):
        w.find_row(ROWS, 0, "")


# ---- what actually gets written ----------------------------------------

class _FakeSheets:
    """Records the batchUpdate it is given instead of calling Google."""

    def __init__(self, rows):
        self.rows, self.written = rows, None

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        self._mode = "get"
        return self

    def batchUpdate(self, spreadsheetId=None, body=None):
        self.written = body
        self._mode = "update"
        return self

    def execute(self):
        return {"values": self.rows} if self._mode == "get" else {}


@pytest.fixture
def sheets(monkeypatch):
    from app.services import csp_gsheet_service
    fake = _FakeSheets(ROWS)
    monkeypatch.setattr(csp_gsheet_service, "_get_sheets_service",
                        lambda: fake)
    return fake


async def test_a_correction_reaches_the_right_cell(sheets):
    written, skipped = w.write_values(
        "1A851727", {"email": "nitasha@example.com"}, tab="CSPData")

    assert written == {"email": "nitasha@example.com"}
    assert skipped == []
    data = sheets.written["data"]
    assert len(data) == 1
    assert data[0]["range"] == "CSPData!D3", "Email Id is column D, Nitasha row 3"
    assert data[0]["values"] == [["nitasha@example.com"]]


async def test_several_fields_go_in_one_write(sheets):
    w.write_values("1A851727",
                   {"gender": "Female", "district": "Panchkula"},
                   tab="CSPData")
    ranges = {d["range"] for d in sheets.written["data"]}
    assert ranges == {"CSPData!E3", "CSPData!G3"}


async def test_a_blank_never_overwrites_a_value(sheets):
    """An empty box means 'nothing to add', never 'delete what you have'."""
    written, _ = w.write_values(
        "1A850466", {"email": "", "gender": "   ", "district": "Saharsa"},
        tab="CSPData")
    assert written == {"district": "Saharsa"}
    assert len(sheets.written["data"]) == 1


async def test_a_submission_of_only_blanks_writes_nothing(sheets):
    written, skipped = w.write_values("1A850466", {"email": "", "gender": ""},
                                      tab="CSPData")
    assert written == {} and skipped == []
    assert sheets.written is None, "an empty write was sent to Google"


async def test_a_field_with_no_column_is_reported_not_dropped(sheets):
    """The caller has just told someone their answer was saved."""
    written, skipped = w.write_values(
        "1A850466", {"gender": "Male", "has_bcp": "Yes"}, tab="CSPData")
    assert written == {"gender": "Male"}
    assert skipped == ["has_bcp"], "the four Has... columns are not in the sheet yet"


async def test_nothing_is_written_when_the_row_is_ambiguous(monkeypatch):
    from app.services import csp_gsheet_service
    fake = _FakeSheets(ROWS + [["1A850466", "Dup", "", "", "", "", "", ""]])
    monkeypatch.setattr(csp_gsheet_service, "_get_sheets_service", lambda: fake)

    with pytest.raises(w.SheetWriteError):
        w.write_values("1A850466", {"gender": "Male"}, tab="CSPData")
    assert fake.written is None, "a write went out despite an ambiguous row"


async def test_an_empty_tab_stops_the_write(monkeypatch):
    from app.services import csp_gsheet_service
    fake = _FakeSheets([])
    monkeypatch.setattr(csp_gsheet_service, "_get_sheets_service", lambda: fake)
    with pytest.raises(w.SheetWriteError, match="empty"):
        w.write_values("1A850466", {"gender": "Male"}, tab="CSPData")


async def test_a_sheet_with_no_code_column_stops_the_write(monkeypatch):
    from app.services import csp_gsheet_service
    fake = _FakeSheets([["CSP Name", "Gender"], ["Abhishek", "Male"]])
    monkeypatch.setattr(csp_gsheet_service, "_get_sheets_service", lambda: fake)
    with pytest.raises(w.SheetWriteError, match="no CSP Code column"):
        w.write_values("1A850466", {"gender": "Male"}, tab="CSPData")
