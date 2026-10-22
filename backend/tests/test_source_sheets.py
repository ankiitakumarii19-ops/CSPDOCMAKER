"""Eko's Calling and Lead raw data sheets (tracker No. 121).

The sheets, CSPDATA and Zoho are replaced by stand-ins: nothing is read
from or written to Google or Zoho. What is checked is the behaviour agreed
on 21 Oct 2026 — old vs new, the moment a CSP goes live, the Zoho fill, and
the hold that stops anything being sent.
"""

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.source_sheet import SourceSheetState
from app.services import sheet_admin_service, source_sheets, zoho_client

pytestmark = pytest.mark.asyncio(loop_scope="session")

KO = get_settings().google_sheets_csp_sheet_name
SUBKO = get_settings().google_sheets_subko_sheet_name


def calling_row(code, name, status="Active", mobile="9000000001"):
    return {"CSP ID": code, "CSP Name": name, "CSP Mobile number": mobile,
            "Gender": "Female", "District": "Patna", "State": "Bihar",
            "Circle (LHO)": "Patna", "Relationship Manager": "Ravi",
            "RBO": "RBO Patna", "Terminal Status": status}


def lead_row(code, name, remarks, mobile="9000000009"):
    return {"CSP Code": code, "CSP Name": name, "Mobile No.": mobile,
            "Gender": "Male", "Branch Code": "1234", "District": "Gaya",
            "State": "", "LHO": "Patna", "Owner (RM)": "Sita",
            "Remarks": remarks}


class Sheets:
    """The three sheets, as the job sees them; keeps what was appended."""

    def __init__(self):
        self.calling, self.lead, self.data = [], [], {KO: [], SUBKO: []}
        self.appended = []
        self.fail = False
        self.address = None          # rows of the Address tab, or None
        self.filled = []

    def read(self, spreadsheet_id, tab, header_row):
        if self.fail:
            raise sheet_admin_service.SheetAdminError("Google is down")
        s = get_settings()
        if tab == s.calling_sheet_tab:
            return list(self.calling)
        if tab == s.lead_sheet_tab:
            return list(self.lead)
        if tab == s.address_sheet_tab:
            return list(self.address or [])
        return list(self.data.get(tab, []))

    def append(self, spreadsheet_id, tab, rows):
        self.appended.extend((tab, dict(r)) for r in rows)
        self.data[tab].extend({"CSP Code": r["CSP Code"]} for r in rows)
        return len(rows)


@pytest.fixture
def world(migrated_db, monkeypatch):
    sheets = Sheets()
    monkeypatch.setattr(source_sheets, "read_rows", sheets.read)
    monkeypatch.setattr(sheet_admin_service, "append_rows", sheets.append)
    monkeypatch.setattr(sheet_admin_service, "list_tabs", lambda sid: (
        [{"title": get_settings().address_sheet_tab}]
        if sheets.address is not None else []))

    def fill(addresses, codes):
        done = [c for c in sorted(codes) if addresses.get(c)
                and c in {r["CSP Code"] for r in sheets.data[KO]}]
        sheets.filled.extend((c, addresses[c]) for c in done)
        return done
    monkeypatch.setattr(source_sheets, "fill_blank_addresses", fill)
    monkeypatch.setattr(zoho_client, "is_configured", lambda: True)
    monkeypatch.setattr(zoho_client, "find_lead", lambda *a, **k: None)
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as s:
        s.execute(text("TRUNCATE source_sheet_states, csp_records "
                       "RESTART IDENTITY CASCADE"))
        s.execute(text("DELETE FROM sync_runs WHERE source = 'address'"))
        s.commit()
        sheets.session = s
        yield sheets
        s.rollback()
        s.execute(text("TRUNCATE source_sheet_states, csp_records "
                       "RESTART IDENTITY CASCADE"))
        s.commit()
    engine.dispose()


def _run(world):
    return source_sheets.run(world.session)


def _state(world, code):
    world.session.expire_all()
    return world.session.execute(select(SourceSheetState).where(
        SourceSheetState.csp_code == code)).scalars().one()


# ---- the first run is a starting point -----------------------------------------

async def test_the_first_run_records_and_copies_old_csps_mails_nobody(world):
    world.calling = [calling_row("1A900001", "Active One"),
                     calling_row("1A900002", "Inactive Two", "Inactive"),
                     calling_row("1A900003", "No Status", ""),
                     calling_row("1A90000X1234X", "Bad Code")]
    world.lead = [lead_row("1A900004", "Live Before", "Go Live Done"),
                  lead_row("1A900002", "Inactive Two", "Go Live Done"),
                  lead_row("1A900005", "Pending", "Hard copy rejected by LHO"),
                  lead_row("", "No Code Yet", "Documents to be prepared")]
    s = _run(world)
    assert s.first_run and s.went_live == [] and s.imported_new == []
    assert s.imported_old == 4, "3 from the Calling sheet + 1 live before"
    added = {r["CSP Code"]: tab for tab, r in world.appended}
    assert set(added) == {"1A900001", "1A900002", "1A900003", "1A900004"}
    assert "1A900005" not in added, "a pending Lead is not added"
    assert any("1A90000X1234X" in x for x in s.skipped)
    assert _state(world, "1A900004").baseline_live is True
    assert all(_state(world, c).imported_as == "baseline"
               for c in ("1A900001", "1A900004"))


async def test_holds_follow_the_sheets(world):
    world.calling = [calling_row("1A900001", "Active One"),
                     calling_row("1A900002", "Inactive Two", "Inactive"),
                     calling_row("1A900003", "No Status", ""),
                     calling_row("1A900006", "Calling But Pending")]
    world.lead = [lead_row("1A900006", "Calling But Pending",
                           "Digital approval pending at branch")]
    _run(world)
    assert _state(world, "1A900001").hold_reason is None
    assert _state(world, "1A900002").hold_reason.startswith(
        "Inactive in the Calling sheet")
    assert _state(world, "1A900003").hold_reason.startswith(
        "No Terminal Status")
    held = _state(world, "1A900006").hold_reason
    assert held.startswith("Not live yet in the Lead raw data sheet"), \
        "the Lead sheet wins while not live"
    assert "Digital approval pending at branch" in held


# ---- going live ----------------------------------------------------------------------

async def test_a_csp_that_goes_live_is_added_as_new_with_zoho_filling_blanks(
        world, monkeypatch):
    world.lead = [lead_row("1A900007", "Asha", "CAT 2 pending")]
    _run(world)                                          # baseline: pending
    assert world.appended == []
    seen = {}

    def find_lead(phone, name="", branch_code=""):
        seen.update(phone=phone, name=name, branch=branch_code)
        return {"id": "L1", "Email": "asha@example.com",
                "Shop_Address_with_Shop_Name": "Ward 4, Gaya",
                "Home_Address": "Not used", "States": "Bihar",
                "Full_Name": "Asha Kumari"}
    monkeypatch.setattr(zoho_client, "find_lead", find_lead)

    world.lead = [lead_row("1A900007", "Asha", "Go Live Done")]
    s = _run(world)
    assert s.went_live == ["1A900007"] and s.imported_new == ["1A900007"]
    [(tab, cells)] = world.appended
    assert tab == KO
    assert seen == {"phone": "9000000009", "name": "Asha", "branch": "1234"}
    assert cells["CSP Email Id"] == "asha@example.com"
    assert cells["Address"] == "Ward 4, Gaya"
    assert cells["State"] == "Bihar", "a blank cell is filled from Zoho"
    assert cells["CSP Name"] == "Asha", "a filled cell is never replaced"
    assert cells["Relationship Manager (RM)"] == "Sita"
    st = _state(world, "1A900007")
    assert st.imported_as == "new" and st.hold_reason is None
    assert st.zoho_filled["CSP Email Id"] == "Email"
    # The sheet sync then creates it as NEW.
    assert source_sheets.state_for_new_record(world.session, "1a900007") == \
        ("new", None)
    assert _run(world).imported_new == [], "added once only"


async def test_a_live_csp_in_the_calling_sheet_stays_old(world):
    world.calling = [calling_row("1A900008", "Old Hand")]
    world.lead = [lead_row("1A900008", "Old Hand", "Hard copy signed by branch")]
    _run(world)
    world.lead = [lead_row("1A900008", "Old Hand", "Go Live Done")]
    s = _run(world)
    assert s.went_live == ["1A900008"] and s.imported_new == []
    assert _state(world, "1A900008").imported_as == "baseline"
    assert _state(world, "1A900008").hold_reason is None, "hold lifted"


async def test_the_rbo_name_comes_from_lead_raw_data_not_the_rbo_number(world):
    world.calling = [{**calling_row("1A900020", "With Lead"), "RBO": "3"},
                     {**calling_row("1A900021", "Calling Only"), "RBO": "2"}]
    world.lead = [{**lead_row("1A900020", "With Lead", "Go Live Done"),
                   "RBO Name": "PAKUR"}]
    _run(world)
    names = {r["CSP Code"]: r["RBO Name"] for _, r in world.appended}
    assert names == {"1A900020": "PAKUR", "1A900021": "RBO 2"}


async def test_a_sub_ko_goes_to_its_tab_and_a_nameless_row_is_skipped(world):
    world.calling = [calling_row("1A90000901", "Sub One"),
                     calling_row("1A900010", "")]
    s = _run(world)
    assert [tab for tab, _ in world.appended] == [SUBKO]
    assert any("1A900010" in x and "no CSP Name" in x for x in s.skipped)


async def test_existing_csp_rows_are_never_rewritten(world):
    world.data[KO] = [{"CSP Code": "1A900011"}]
    world.calling = [calling_row("1A900011", "Already There")]
    _run(world)
    assert world.appended == []


async def test_a_sheet_that_cannot_be_read_changes_nothing(world):
    world.fail = True
    with pytest.raises(sheet_admin_service.SheetAdminError):
        _run(world)
    world.session.rollback()
    assert world.session.execute(select(SourceSheetState)).first() is None


# ---- the hold, on the CSP's record ----------------------------------------------------

async def test_the_hold_is_put_on_and_lifted_on_the_csp_record(world):
    world.session.add(CSPRecord(csp_id="1A900012", csp_code="1A900012",
                                name="Held", origin="baseline"))
    world.session.commit()
    world.data[KO] = [{"CSP Code": "1A900012"}]
    world.calling = [calling_row("1A900012", "Held", "Inactive")]
    _run(world)
    world.session.expire_all()
    csp = world.session.execute(select(CSPRecord)).scalars().one()
    assert csp.send_hold.startswith("Inactive in the Calling sheet")
    world.calling = [calling_row("1A900012", "Held", "Active")]
    _run(world)
    world.session.expire_all()
    assert world.session.execute(select(CSPRecord)).scalars().one(
    ).send_hold is None


async def test_nothing_is_sent_to_a_csp_on_hold(world, client, monkeypatch):
    from app.services import (assistant_tools, documents_whatsapp,
                              message_sender, jwt_service)
    from app.models.enums import AccountStatus, UserRole
    from app.models.user import User
    world.session.execute(text("DELETE FROM users WHERE email = "
                               "'rm.hold@eko.co.in'"))
    world.session.add(User(email="rm.hold@eko.co.in", name="RM Hold",
                           mobile="9876543210", role=UserRole.RM,
                           account_status=AccountStatus.ACTIVE,
                           password_hash="x"))
    world.session.add(CSPRecord(csp_id="1A900013", csp_code="1A900013",
                                name="On Hold", origin="new",
                                mobile="9000000013",
                                send_hold="Inactive in the Calling sheet — "
                                          "nothing is sent until it is Active."))
    world.session.commit()
    csp = world.session.execute(select(CSPRecord)).scalars().one()

    # Asking the CSP for details (WhatsApp / email / campaigns / agent).
    out = message_sender.ask_for_details(world.session, csp)
    assert out["sent"] is False and out["reason"].startswith("Inactive")
    # The documents-ready WhatsApp.
    out = documents_whatsapp.notify(world.session, csp, None, ["x"])
    assert out == {"status": "skipped", "reason": csp.send_hold}

    token = jwt_service.create_access_token(
        {"sub": "admin@eko.co.in", "role": "admin", "name": "Admin"})
    h = {"Authorization": f"Bearer {token}"}
    # An RM's request for documents (an unassigned CSP: every RM sees it).
    rm = {"Authorization": "Bearer " + jwt_service.create_access_token(
        {"sub": "rm.hold@eko.co.in", "role": "rm", "name": "RM Hold"})}
    r = await client.post("/api/workflows/process", headers=rm, json={
        "csp_id": "1A900013", "document_types": ["csp_id_card"]})
    assert r.status_code == 409 and "Inactive in the Calling sheet" in r.text, r.text
    # The CSP's details show the hold.
    r = await client.get("/api/csps/1A900013", headers=h)
    assert r.json()["send_hold"].startswith("Inactive")
    # The chat will not draft a message.
    monkeypatch.setattr(assistant_tools, "_redis", None)
    r = await client.post("/api/assistant/chat", headers=h, json={
        "messages": [{"role": "user",
                      "content": "Message 1A900013: please call me"}]})
    assert r.json()["cards"] == []
    assert "Nothing can be sent" in r.json()["reply"]


# ---- the temporary Address tab (No. 129) ----------------------------------------

async def test_old_csps_get_their_address_from_the_address_tab(world):
    world.address = [{"CSP Code": "1A900030", "Address": "Ward 3, Patna 800001"},
                     {"CSP Code": "1A900099", "Address": "Not in any sheet"}]
    world.data[KO] = [{"CSP Code": "1A900031"}]       # was in CSPDATA already
    world.calling = [calling_row("1A900030", "Copied In"),
                     calling_row("1A900031", "Already There")]
    s = _run(world)
    added = {r["CSP Code"]: r for _, r in world.appended}
    assert added["1A900030"]["Address"] == "Ward 3, Patna 800001"
    assert "1A900031" not in added, "a CSP already in CSPDATA is never edited"
    assert ("1A900031", "Ward 3, Patna 800001") not in world.filled
    from app.models.sync_run import SyncRun
    world.session.expire_all()
    assert world.session.execute(select(SyncRun).where(
        SyncRun.source == "address")).scalars().first() is not None


async def test_the_address_tab_fills_old_csps_copied_in_earlier(world):
    world.calling = [calling_row("1A900032", "Earlier")]
    _run(world)                                   # copied in, no address yet
    world.address = [{"CSP Code": "1A900032", "Full Address": "Ward 9, Gaya"}]
    s = _run(world)
    assert world.filled == [("1A900032", "Ward 9, Gaya")]
    assert s.addresses_filled == 1


async def test_without_the_address_tab_nothing_changes(world):
    world.calling = [calling_row("1A900033", "No Tab")]
    s = _run(world)
    assert s.addresses_filled == 0 and world.filled == []
    from app.models.sync_run import SyncRun
    world.session.expire_all()
    assert world.session.execute(select(SyncRun).where(
        SyncRun.source == "address")).scalars().first() is None


async def test_only_empty_address_cells_of_listed_codes_are_written(monkeypatch):
    """fill_blank_addresses itself, against a stand-in Google service."""
    sent = {}
    rows = [["CSP Code", "CSP Name", "Address"],
            ["1A900040", "Empty", ""],
            ["1A900041", "Has One", "Old address"],
            ["1A900042", "Not Listed", ""]]

    class Call:
        def __init__(self, result):
            self.result = result

        def execute(self):
            return self.result

    class Values:
        def get(self, spreadsheetId, range):
            return Call({"values": rows if "SUBKO" not in range else []})

        def batchUpdate(self, spreadsheetId, body):
            sent["data"] = body["data"]
            return Call({})

    class Service:
        def spreadsheets(self):
            return self

        def values(self):
            return Values()

    monkeypatch.setattr(sheet_admin_service, "_service", lambda: Service())
    written = source_sheets.fill_blank_addresses(
        {"1A900040": "New A", "1A900041": "New B", "1A900042": "New C"},
        {"1A900040", "1A900041"})
    assert written == ["1A900040"]
    assert sent["data"] == [{"range": "KOData!C2", "values": [["New A"]]}]
