"""Finding a CSP's KYC pack in Zoho.

A CSP can exist in two places. sbi_kiosk carries the CSP code but usually no
files; Leads carries the KYC pack but no CSP code. Both must always be
consulted, and a Lead must be identified without a code to rely on.

The failure these guard against is attaching the wrong person's photograph
to a document, so a Lead is accepted only when two independent facts agree.
"""

import pytest

from app.services import zoho_client as z

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _lead(**fields):
    base = {"id": "1", "Full_Name": "", "Phone": "", "Branch_Code": ""}
    base.update(fields)
    return base


# ---- how a Lead is identified ------------------------------------------

async def test_phone_and_name_together_identify_a_lead():
    record = _lead(Full_Name="Nitasha", Phone="9812345670")
    assert z._lead_matches(record, "9812345670", "nitasha", "")


async def test_phone_and_branch_together_identify_a_lead():
    record = _lead(Full_Name="Someone Else", Phone="9812345670",
                   Branch_Code="12204")
    assert z._lead_matches(record, "9812345670", "nitasha", "12204")


async def test_name_and_branch_identify_a_lead_when_the_phone_differs():
    """The sheet and the CRM disagree about phone numbers in real data."""
    record = _lead(Full_Name="Nitasha", Phone="9999999999",
                   Branch_Code="12204")
    assert z._lead_matches(record, "9812345670", "nitasha", "12204")


async def test_the_name_alone_is_never_enough():
    """Four different Leads are called Harimohan."""
    record = _lead(Full_Name="Harimohan Kumar", Phone="7667318374")
    assert not z._lead_matches(record, "9472135351", "harimohan kumar", "4654")


async def test_the_phone_alone_is_never_enough():
    record = _lead(Full_Name="Someone Else", Phone="9812345670")
    assert not z._lead_matches(record, "9812345670", "nitasha", "12204")


async def test_the_branch_alone_is_never_enough():
    """A branch has many CSPs."""
    record = _lead(Full_Name="Pushpa Kumari", Phone="9234008289",
                   Branch_Code="4654")
    assert not z._lead_matches(record, "9472135351", "harimohan kumar", "4654")


async def test_matching_ignores_case_and_spacing():
    record = _lead(Full_Name="  NITASHA  ", Phone="+91 98123 45670")
    assert z._lead_matches(record, "9812345670", "nitasha", "")


# ---- Leads is always consulted -----------------------------------------

async def test_leads_is_searched_by_phone_and_by_name(monkeypatch):
    """Either identifier can disagree with the sheet, so both are tried."""
    calls = []

    def fake_search(**params):
        calls.append(params)
        return []

    monkeypatch.setattr(z, "_lead_search", fake_search)
    z.find_lead("9472135351", "Harimohan Kumar", "4654")

    assert any("phone" in c for c in calls), "Leads was not searched by phone"
    assert any("criteria" in c for c in calls), "Leads was not searched by name"


async def test_a_csp_in_both_modules_still_reaches_the_lead(monkeypatch):
    """The bug this replaces: stopping at the first match.

    sbi_kiosk matches on code and phone but carries no files, so returning
    only that record meant the Lead's KYC pack was never reached.
    """
    kiosk = {"id": "kiosk-1"}
    lead = {"id": "lead-1"}
    monkeypatch.setattr(z, "find_csp", lambda phone, code: kiosk)
    monkeypatch.setattr(z, "find_lead", lambda phone, name, branch: lead)

    class _CSP:
        csp_id, mobile, name, branch_code = "1A999999", "9000000000", "X", "1"

    found = z.find_csp_records(_CSP())
    assert [m for m, _ in found] == [z.MODULE, z.LEADS_MODULE]
    assert [r["id"] for _, r in found] == ["kiosk-1", "lead-1"]


async def test_leads_is_consulted_even_when_sbi_kiosk_matches(monkeypatch):
    asked = {"lead": False}

    def fake_lead(phone, name, branch):
        asked["lead"] = True
        return None

    monkeypatch.setattr(z, "find_csp", lambda phone, code: {"id": "kiosk-1"})
    monkeypatch.setattr(z, "find_lead", fake_lead)

    class _CSP:
        csp_id, mobile, name, branch_code = "1A999999", "9000000000", "X", "1"

    z.find_csp_records(_CSP())
    assert asked["lead"], "Leads must be consulted even on an sbi_kiosk hit"


async def test_no_match_anywhere_returns_nothing(monkeypatch):
    monkeypatch.setattr(z, "find_csp", lambda phone, code: None)
    monkeypatch.setattr(z, "find_lead", lambda phone, name, branch: None)

    class _CSP:
        csp_id, mobile, name, branch_code = "1A999999", "9000000000", "X", "1"

    assert z.find_csp_records(_CSP()) == []
