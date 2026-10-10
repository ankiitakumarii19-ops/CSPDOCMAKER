"""Authorization-sheet rules, against the real sheet's column layout:

    Sn_no | Name | Email_id | Contact_no | Status
"""

import pytest

from app.services import google_sheets_service as gs

HEADERS = ["Sn_no", "Name ", "Email_id", "Contact_no", "Status"]


def _rows(*data):
    return [HEADERS, *data]


@pytest.fixture
def sheet(monkeypatch):
    """Patch the sheet reader so no network call is made."""
    def use(rows):
        monkeypatch.setattr(gs, "_read_sheet_tab", lambda name: rows)
    return use


def test_active_user_is_authorized(sheet):
    sheet(_rows(["1", "Rm One", "rm.one@eko.co.in", "9876543210", "Active"]))
    authorized, data = gs.check_authorization("rm.one@eko.co.in", "rm")
    assert authorized
    assert gs.get_field(data, "Contact_no") == "9876543210"


@pytest.mark.parametrize("status", ["Inactive", "", "Removed", "active-pending"])
def test_non_active_status_is_denied(sheet, status):
    sheet(_rows(["1", "Rm One", "rm.one@eko.co.in", "9876543210", status]))
    authorized, data = gs.check_authorization("rm.one@eko.co.in", "rm")
    assert authorized is False and data is None


def test_status_match_ignores_case_and_spacing(sheet):
    sheet(_rows(["1", "Rm One", "rm.one@eko.co.in", "9876543210", " ACTIVE "]))
    assert gs.check_authorization("rm.one@eko.co.in", "rm")[0] is True


def test_unknown_email_is_denied(sheet):
    sheet(_rows(["1", "Rm One", "rm.one@eko.co.in", "9876543210", "Active"]))
    assert gs.check_authorization("someone.else@eko.co.in", "rm")[0] is False


def test_incomplete_row_is_denied(sheet):
    # The live RMs tab currently has rows with only Sn_no filled in.
    sheet(_rows(["1"], ["2"], ["3"]))
    assert gs.check_authorization("rm.one@eko.co.in", "rm")[0] is False


def test_get_field_handles_real_header_spelling():
    row = {"Sn_no": "1", "Name ": "Rm One", "Email_id": "a@eko.co.in",
           "Contact_no": "9876543210", "Status": "Active"}
    # Regression: the old code looked for 'mobile'/'phone' and never matched
    # 'Contact_no', so the signup mobile was always empty.
    assert gs.get_field(row, "Contact_no", "Mobile", "Phone") == "9876543210"
    assert gs.get_field(row, "Name") == "Rm One"
    assert gs.get_field(row, "Missing_column") == ""
