"""Zoho CRM lookups.

Zoho itself is mocked: these cover the decisions the client makes about the
CRM's real shape, which was confirmed against the live account —

  * the CSP code lives in CSP_Code1 on some records and SBI_Code on others,
    and CSP_Code1 sometimes holds a plain internal number instead;
  * many records carry no mobile number at all;
  * access tokens must be cached, because Zoho rate-limits refreshes.
"""

import time

import pytest

from app.services import zoho_client


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """Pretend credentials exist, and clear the cached token between tests."""
    monkeypatch.setattr(zoho_client.settings, "zoho_client_id", "id")
    monkeypatch.setattr(zoho_client.settings, "zoho_client_secret", "secret")
    monkeypatch.setattr(zoho_client.settings, "zoho_refresh_token", "refresh")
    monkeypatch.setattr(zoho_client, "_token", None)
    monkeypatch.setattr(zoho_client, "_token_expires_at", 0.0)


@pytest.fixture
def searches(monkeypatch):
    """Stand in for Zoho, answering phone and code searches separately.

    The two must be distinguishable: find_csp tries the phone first and only
    falls back to the code, and a mock that answers both identically would
    hide which path actually returned the record.
    """
    calls = {"criteria": [], "records": [], "by_phone": None, "by_code": None}

    def fake_search(criteria):
        calls["criteria"].append(criteria)
        is_phone = any(f"({field}:" in criteria for field in zoho_client.PHONE_FIELDS)
        specific = calls["by_phone"] if is_phone else calls["by_code"]
        return specific if specific is not None else calls["records"]

    monkeypatch.setattr(zoho_client, "_search", fake_search)
    return calls


# ---- token caching -------------------------------------------------------

def test_the_access_token_is_cached(monkeypatch):
    """Zoho throttles refreshes, so one token must serve many calls."""
    refreshes = []

    class _Response:
        @staticmethod
        def json():
            refreshes.append(1)
            return {"access_token": "abc", "expires_in": 3600}

    monkeypatch.setattr(zoho_client.httpx, "post", lambda *a, **k: _Response())

    assert zoho_client.access_token() == "abc"
    assert zoho_client.access_token() == "abc"
    assert zoho_client.access_token() == "abc"
    assert len(refreshes) == 1, "the token was refreshed more than once"


def test_an_expired_token_is_refreshed(monkeypatch):
    refreshes = []

    class _Response:
        @staticmethod
        def json():
            refreshes.append(1)
            return {"access_token": f"tok{len(refreshes)}", "expires_in": 3600}

    monkeypatch.setattr(zoho_client.httpx, "post", lambda *a, **k: _Response())
    zoho_client.access_token()
    monkeypatch.setattr(zoho_client, "_token_expires_at", time.time() - 1)
    assert zoho_client.access_token() == "tok2"


def test_the_rate_limit_is_reported_in_plain_words(monkeypatch):
    class _Response:
        @staticmethod
        def json():
            return {"error": "Access Denied"}

    monkeypatch.setattr(zoho_client.httpx, "post", lambda *a, **k: _Response())
    with pytest.raises(zoho_client.ZohoError, match="rate limit"):
        zoho_client.access_token()


def test_missing_credentials_are_a_clear_error(monkeypatch):
    monkeypatch.setattr(zoho_client.settings, "zoho_refresh_token", "")
    with pytest.raises(zoho_client.ZohoNotConfigured):
        zoho_client.access_token()


# ---- reading the CSP code off a record -----------------------------------

def test_the_code_is_read_from_csp_code1():
    assert zoho_client.record_csp_code({"CSP_Code1": "1A852411"}) == "1A852411"


def test_the_code_is_read_from_sbi_code_when_csp_code1_is_internal():
    """Real record: CSP_Code1 holds 11403160, SBI_Code holds the real code."""
    record = {"CSP_Code1": "11403160", "SBI_Code": "1A851767"}
    assert zoho_client.record_csp_code(record) == "1A851767"


def test_a_record_with_no_code_yields_none():
    assert zoho_client.record_csp_code({"CSP_Code1": None, "SBI_Code": None}) is None


# ---- searching -----------------------------------------------------------

def test_a_phone_search_covers_every_phone_field(searches):
    zoho_client.find_by_phone("9812345671")
    criteria = searches["criteria"][0]
    for field in zoho_client.PHONE_FIELDS:
        assert f"({field}:equals:9812345671)" in criteria


def test_a_phone_number_is_reduced_to_its_last_ten_digits(searches):
    zoho_client.find_by_phone("+91 98123 45671")
    assert "9812345671" in searches["criteria"][0]


def test_an_unusable_phone_number_is_not_searched(searches):
    assert zoho_client.find_by_phone("123") == []
    assert searches["criteria"] == [], "a hopeless number still hit the API"


def test_a_code_search_covers_both_code_fields(searches):
    zoho_client.find_by_csp_code("1A850466")
    criteria = searches["criteria"][0]
    assert "(CSP_Code1:equals:1A850466)" in criteria
    assert "(SBI_Code:equals:1A850466)" in criteria


# ---- find_csp: the sequence the photo pipeline uses ----------------------

def test_a_phone_match_must_also_match_the_code(searches):
    """Confirming the code is what stops the wrong person's document."""
    searches["by_phone"] = [{"id": "1", "CSP_Code1": "1A999999",
                             "Mobile_Number": "9812345671"}]
    searches["by_code"] = []
    assert zoho_client.find_csp("9812345671", "1A850466") is None


def test_a_matching_record_is_returned(searches):
    searches["records"] = [{"id": "7", "CSP_Code1": "1A850466",
                            "Mobile_Number": "9812345671"}]
    found = zoho_client.find_csp("9812345671", "1A850466")
    assert found["id"] == "7"


def test_a_record_without_a_phone_number_is_refused(searches):
    """Confirmed rule: the code AND the phone must both match.

    Many CRM records carry no mobile at all, so this refuses a lot of them —
    deliberately. An unverifiable record goes to the RM instead of being
    assumed to be the right person.
    """
    searches["by_phone"] = []
    searches["by_code"] = [{"id": "9", "SBI_Code": "1A850466",
                            "Mobile_Number": ""}]
    assert zoho_client.find_csp("9812345671", "1A850466") is None


def test_a_record_matching_on_code_and_phone_is_accepted(searches):
    searches["by_phone"] = []
    searches["by_code"] = [{"id": "9", "SBI_Code": "1A850466",
                            "Mobile_Number": "9812345671"}]
    assert zoho_client.find_csp("9812345671", "1A850466")["id"] == "9"


def test_the_phone_may_match_any_of_the_phone_fields(searches):
    searches["by_phone"] = []
    searches["by_code"] = [{"id": "9", "SBI_Code": "1A850466",
                            "Mobile_Number": "9000000000",
                            "WhasApp_Number": "+91 98123 45671"}]
    assert zoho_client.find_csp("9812345671", "1A850466")["id"] == "9"


def test_a_code_match_whose_phone_contradicts_is_refused(searches):
    searches["by_phone"] = []
    searches["by_code"] = [{"id": "3", "SBI_Code": "1A850466",
                            "Mobile_Number": "9000000000"}]
    assert zoho_client.find_csp("9812345671", "1A850466") is None


def test_the_fallback_rechecks_the_code_it_was_given(searches):
    """Never trust the search to have filtered correctly."""
    searches["by_phone"] = []
    searches["by_code"] = [{"id": "5", "SBI_Code": "1A111111",
                            "Mobile_Number": ""}]
    assert zoho_client.find_csp("9812345671", "1A850466") is None


def test_nothing_found_is_none(searches):
    searches["records"] = []
    assert zoho_client.find_csp("9812345671", "1A850466") is None
