"""Zoho first, then the CSP (tracker No. 124).

Before a CSP is WhatsApped for missing details, the typed fields of their
Zoho Lead fill what they can; only what is still missing is asked. Zoho and
the sheet are stand-ins: nothing leaves the test.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.services import (data_request_service as drs, message_sender,
                          sheet_writeback_service as wb, zoho_client,
                          zoho_fill)

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def db(migrated_db):
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as s:
        s.execute(text("TRUNCATE data_requests, csp_records "
                       "RESTART IDENTITY CASCADE"))
        s.commit()
        yield s
        s.rollback()
        s.execute(text("TRUNCATE data_requests, csp_records "
                       "RESTART IDENTITY CASCADE"))
        s.commit()
    engine.dispose()


@pytest.fixture
def zoho(monkeypatch):
    state = {"lead": {"id": "L9", "Email": "asha@example.com",
                      "Shop_Address_with_Shop_Name": "Ward 4, Gaya, 823001",
                      "Home_Address": "Not used, 999999",
                      "States": "Bihar", "Gender": ""},
             "written": [], "sheet_fails": False}

    def write(code, values, *a, **k):
        if state["sheet_fails"]:
            raise wb.SheetWriteError("Google is down")
        state["written"].append((code, dict(values)))
        return dict(values), []
    monkeypatch.setattr(zoho_client, "is_configured", lambda: True)
    monkeypatch.setattr(zoho_client, "find_lead", lambda *a, **k: state["lead"])
    monkeypatch.setattr(wb, "write_values", write)
    return state


def _csp(db, **kw):
    record = CSPRecord(csp_id="1A930001", name="Asha", mobile="9000000001",
                       branch_code="1234", **kw)
    db.add(record)
    db.commit()
    return record


async def test_blanks_are_filled_from_zoho_and_written_to_the_sheet(db, zoho):
    record = _csp(db, state="Jharkhand")
    filled = zoho_fill.fill_from_zoho(db, record)
    assert filled == {"email": "asha@example.com",
                      "address": "Ward 4, Gaya, 823001"}
    assert record.state == "Jharkhand", "a filled field is never replaced"
    assert zoho["written"] == [("1A930001", filled)]


async def test_nothing_is_filled_if_the_sheet_cannot_be_updated(db, zoho):
    zoho["sheet_fails"] = True
    record = _csp(db)
    assert zoho_fill.fill_from_zoho(db, record) == {}
    assert record.email is None, "the sync would wipe a value set only here"


async def test_no_lead_or_no_mobile_fills_nothing(db, zoho):
    zoho["lead"] = None
    assert zoho_fill.fill_from_zoho(db, _csp(db)) == {}


def _channel_and_template(monkeypatch):
    monkeypatch.setattr(message_sender, "choose_channel", lambda s: SimpleNamespace(
        kind="whatsapp", last_used_at=None, last_error=None))
    monkeypatch.setattr(message_sender, "choose_template", lambda s: SimpleNamespace(
        body="Namaste {name} {link} {fields}", subject=None,
        purpose="data_request"))


async def test_the_csp_is_not_messaged_when_zoho_had_everything(
        db, zoho, monkeypatch):
    _channel_and_template(monkeypatch)
    monkeypatch.setattr(drs, "fields_to_ask",
                        lambda r: [] if r.email and r.address else
                        ["email", "address"])
    from app.services import whatsapp_platform
    sent = []
    monkeypatch.setattr(whatsapp_platform, "send",
                        lambda *a, **k: sent.append(1))
    out = message_sender.ask_for_details(db, _csp(db))
    assert out["sent"] is False
    assert out["reason"] == "nothing is missing from their own details"
    assert sent == []


async def test_only_what_zoho_lacks_is_asked(db, zoho, monkeypatch):
    zoho["lead"] = {"id": "L9", "Email": "asha@example.com"}
    _channel_and_template(monkeypatch)
    asked = {}
    monkeypatch.setattr(drs, "fields_to_ask", lambda r: [
        f for f in ("email", "address") if not getattr(r, f)])
    monkeypatch.setattr(message_sender, "address_for",
                        lambda r, kind: ("", "whatsapp"))  # stop before sending
    record = _csp(db)
    out = message_sender.ask_for_details(db, record)
    assert record.email == "asha@example.com"
    assert drs.fields_to_ask(record) == ["address"]
    assert out["reason"] == "no usable mobile number and no email address"


# ---- the address: Shop / Business Address, never Home Address (22 Oct 2026) ----

def test_the_shop_address_box_comes_first():
    lead = {"Shop_Address_with_Shop_Name": " Asha Store, Ward 4, Gaya 823001 ",
            "Street": "Main Road", "City": "Gaya",
            "Home_Address": "Home, not used"}
    assert zoho_client.lead_address(lead) == "Asha Store, Ward 4, Gaya 823001"


def test_else_the_business_address_is_put_together():
    lead = {"Shop_Name": "Asha Store", "Street": "Main Road, Ward 4",
            "Landmark": "Near Hanuman Mandir", "City": "Gaya",
            "States": "Bihar", "Zip_Code": 823001, "Country": "India",
            "Home_Address": "Home, not used"}
    assert zoho_client.lead_address(lead) == (
        "Asha Store, Main Road, Ward 4, Near Hanuman Mandir, Gaya, "
        "Bihar 823001")


def test_a_shop_box_with_no_number_is_not_an_address():
    lead = {"Shop_Address_with_Shop_Name": "Online shop", "City": "Gaya",
            "States": "Bihar", "Zip_Code": "823001"}
    assert zoho_client.lead_address(lead) == ""
    lead["Street"] = "Ward 4, Main Road"
    assert zoho_client.lead_address(lead) == \
        "Ward 4, Main Road, Gaya, Bihar 823001"


def test_a_city_state_and_pin_alone_is_not_an_address():
    lead = {"City": "Gaya", "States": "Bihar", "Zip_Code": "823001",
            "Home_Address": "Ward 4, Gaya"}
    assert zoho_client.lead_address(lead) == "", \
        "the CSP is asked; Home Address is never used"


async def test_the_csp_gets_the_business_address_from_zoho(db, zoho):
    zoho["lead"] = {"id": "L9", "Street": "Main Road", "City": "Gaya",
                    "States": "Bihar", "Zip_Code": "823001",
                    "Home_Address": "Not used"}
    record = _csp(db)
    filled = zoho_fill.fill_from_zoho(db, record)
    assert filled["address"] == "Main Road, Gaya, Bihar 823001"
    assert record.address == "Main Road, Gaya, Bihar 823001"
