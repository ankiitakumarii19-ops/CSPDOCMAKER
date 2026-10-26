"""One CSP, the whole way through (tracker No. 121, 123, 124, 125).

"Go Live Done" in Zero to Hero → added to KOData as NEW → the app creates
the CSP → Zoho fills what it has → the CSP is WhatsApped for the rest →
they answer on their form → the answer reaches the sheet → the documents
are made and mailed.

Real: the source-sheets job, the sheet sync, the new-CSP job, the details
form and document making. Stand-ins: Google Sheets (an in-memory KOData),
Zoho, WhatsApp, email, and the CRM photo. Nothing leaves the test.
"""

import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.services import (csp_mapping, sheet_admin_service, source_sheets,
                          zoho_client)

pytestmark = pytest.mark.asyncio(loop_scope="session")

CODE = "1A955501"
KO = get_settings().google_sheets_csp_sheet_name


class World:
    def __init__(self):
        self.lead = [{"CSP Code": CODE, "CSP Name": "Asha Devi",
                      "Mobile No.": "9000000501", "Gender": "Female",
                      "Branch Name": "Riga", "Branch Code": "12564",
                      "Branch Contact No.": "9000000502",
                      "District": "Sitamarhi", "State": "Bihar",
                      "AO": "AO Muzaffarpur", "LHO": "Patna",
                      "Owner (RM)": "Kavya Shukla", "ASM": "Munna Pathak",
                      "RBO Name": "Madhubani",
                      "RBO Contact No.": "9000000503",
                      "Remarks": "Hard copy signed by branch"}]
        self.calling = []         # the Calling sheet (old CSPs)
        self.koda = {}            # code -> {KOData header: value}
        self.whatsapp = []
        self.emails = []


@pytest.fixture
def world(migrated_db, monkeypatch):
    from app.services import (csp_gsheet_service, csp_photo_service,
                              email_service, message_sender,
                              sheet_photo_reader, sheet_writeback_service,
                              whatsapp_platform)
    from app.services import info_directory

    w = World()

    # Google Sheets
    def read_rows(sid, tab, header_row):
        s = get_settings()
        if tab == s.lead_sheet_tab:
            return [dict(r) for r in w.lead]
        if tab == s.calling_sheet_tab:
            return [dict(r) for r in w.calling]
        return [dict(r) for r in w.koda.values()] if tab == KO else []

    def append_rows(sid, tab, rows):
        for r in rows:
            w.koda[r["CSP Code"]] = dict(r)
        return len(rows)

    def write_values(code, values, *a, **k):
        row = w.koda[code]
        for field, value in values.items():
            row[csp_mapping.FIELD_TO_SHEET_COLUMN[field].strip()] = value
        return dict(values), []

    monkeypatch.setattr(source_sheets, "read_rows", read_rows)
    monkeypatch.setattr(sheet_admin_service, "append_rows", append_rows)
    monkeypatch.setattr(sheet_admin_service, "list_tabs", lambda sid: [])
    monkeypatch.setattr(csp_gsheet_service, "read_csp_sheet",
                        lambda: [dict(r) for r in w.koda.values()])
    monkeypatch.setattr(sheet_writeback_service, "write_values", write_values)

    class FakeInfo:
        """The INFO tab: DC by district, ASM by territory."""
        def fill_missing(self, mapped, why=None):
            out = {}
            for field, value in (("dc", "Anish Kumar"),
                                 ("dc_email", "anish@example.com"),
                                 ("dc_contact", "9000000504"),
                                 ("asm_email", "munna@example.com"),
                                 ("asm_contact", "9000000505"),
                                 ("asm_name", "Munna Pathak")):
                if not mapped.get(field):
                    out[field] = value
                    if why is not None:
                        why[field] = "INFO (test stand-in)"
            return out

        def find_by_territory(self, *a, **k):
            return None

        def find_by_district(self, *a, **k):
            return None
    monkeypatch.setattr(info_directory.InfoDirectory, "load",
                        staticmethod(lambda: FakeInfo()))

    # Zoho: a Lead with an email typed in, no address.
    monkeypatch.setattr(zoho_client, "is_configured", lambda: True)
    monkeypatch.setattr(zoho_client, "find_lead", lambda *a, **k: {
        "id": "L501", "Email": "asha.devi@example.com"})
    for source in (sheet_photo_reader, csp_photo_service):
        monkeypatch.setattr(source, "fetch_photo", lambda csp: SimpleNamespace(
            ok=False, path=None, message="no photo in this test"))

    # WhatsApp and email
    monkeypatch.setattr(message_sender, "choose_channel",
                        lambda s: SimpleNamespace(kind="whatsapp",
                                                  last_used_at=None,
                                                  last_error=None))
    monkeypatch.setattr(message_sender, "choose_template",
                        lambda s: SimpleNamespace(
                            body="Namaste {name}, please fill: {fields} {link}",
                            subject=None, purpose="missing_data"))
    monkeypatch.setattr(message_sender, "link_is_reachable", lambda link: True)

    def send(to, body, values, **k):
        w.whatsapp.append({"to": to, **values})
        return {"status": whatsapp_platform.SENT, "reason": "",
                "job_id": f"job{len(w.whatsapp)}", "template_name": "t"}
    monkeypatch.setattr(whatsapp_platform, "send", send)
    monkeypatch.setattr(email_service, "send_documents_email",
                        lambda **kw: (w.emails.append(kw), True)[1])

    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as s:
        s.execute(text("TRUNCATE source_sheet_states, "
                       "data_requests, rm_alerts, whatsapp_messages, "
                       "stored_documents, csp_records "
                       "RESTART IDENTITY CASCADE"))
        s.commit()
        w.session = s
        yield w
        s.rollback()
        s.execute(text("TRUNCATE source_sheet_states, "
                       "data_requests, rm_alerts, whatsapp_messages, "
                       "stored_documents, csp_records "
                       "RESTART IDENTITY CASCADE"))
        s.commit()
    engine.dispose()


def _only(outcome):
    first = outcome["results"][0]
    assert "error" not in first, first.get("error")
    return first["result"]


def _sync():
    from app.workers import csp_sync_worker
    return _only(csp_sync_worker.sync_csp_data.apply().get())


def _new_csps():
    from app.workers import new_csp_worker
    return _only(new_csp_worker.process_new_csps.apply().get())


def _record(w):
    w.session.expire_all()
    return w.session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == CODE)).scalars().one()


async def test_go_live_to_documents_mailed(world, client):
    w = world
    # 1. Pending: nothing added, nothing sent.
    source_sheets.run(w.session)
    assert w.koda == {}

    # 2. The remark changes to "Go Live Done".
    w.lead[0]["Remarks"] = "Go Live Done"
    s = source_sheets.run(w.session)
    assert s.imported_new == [CODE]
    assert w.koda[CODE]["Relationship Manager (RM)"] == "Kavya Shukla"

    # 3. The sheet sync creates the CSP as NEW, not on hold.
    _sync()
    csp = _record(w)
    assert csp.origin == "new" and csp.send_hold is None

    # 4. The new-CSP job: Zoho fills the email, the CSP is WhatsApped for
    #    the rest, and the RM is told — no document yet.
    out = _new_csps()
    assert out["documents_sent"] == 0
    csp = _record(w)
    assert csp.email == "asha.devi@example.com", "filled from Zoho"
    assert w.koda[CODE]["CSP Email Id"] == "asha.devi@example.com", \
        "written to the sheet, so the sync keeps it"
    [ask] = w.whatsapp
    assert ask["to"].endswith("9000000501")
    asked_for = ask["fields"].split(", ")
    from app.services import field_ownership as fo
    assert "Address" in asked_for
    assert fo.label_of("email") not in asked_for, "Zoho had the email"
    assert not {fo.label_of(f) for f in ("dc", "dc_email", "asm_email",
                                         "asm_contact", "rm_name", "lho",
                                         "ao", "rbo_name")} & set(asked_for), \
        "only the CSP's own details (AO / RBO were mapped from the sheet)"

    # 5. The next run does not ask again.
    _new_csps()
    assert len(w.whatsapp) == 1, "asked once only"

    # 6. The CSP answers on their form.
    token = re.search(r"([A-Za-z0-9_\-]{20,})\s*$", ask["link"]).group(1)
    form = (await client.get(f"/api/csp-form/{token}")).json()
    answers = {f["name"]: f"Ward 7, Pakari, Sitamarhi, Bihar, 843327"
               if f["name"] == "address" else (f["value"] or "Filled 9000000599")
               for f in form["fields"] if f["type"] != "photo"}
    r = await client.post(f"/api/csp-form/{token}", json={"values": answers})
    assert r.status_code == 200, r.text
    assert w.koda[CODE]["Address"] == "Ward 7, Pakari, Sitamarhi, Bihar, 843327"

    # 7. The sync keeps the answer; the next run makes and mails the documents.
    _sync()
    out = _new_csps()
    assert out["documents_sent"] == 1, out
    [mail] = w.emails
    assert mail["to_email"] == "asha.devi@example.com"
    assert mail["csp_id"] == CODE and len(mail["doc_names"]) >= 3
    assert _record(w).new_csp_processed_at is not None


# ---- an old CSP: verification WhatsApp, answer, documents (No. 134) ----------

OLD = "1A955601"


async def test_an_old_csp_gets_documents_once_they_answer(world, client,
                                                          monkeypatch):
    from datetime import datetime, timezone

    from app.workers import verify_old_csps_worker as verify
    w = world
    monkeypatch.setattr(get_settings(), "verify_wait_for_address", False)
    w.calling = [{"CSP ID": OLD, "CSP Name": "Ramesh Kumar",
                  "CSP Mobile number": "9000000601",
                  "CSP Mail ID": "ramesh@example.com", "Gender": "Male",
                  "Branch Name": "Pakur Bazar", "Branch Code": "12345",
                  "Full Address": "Ward 4, Pakur, Jharkhand 816107",
                  "District": "Pakur", "State": "Jharkhand", "AO": "AO Dumka",
                  "Circle (LHO)": "Patna", "Relationship Manager": "Ravi",
                  "RBO": "RBO Dumka", "Terminal Status": "Active"}]

    # Copied in from the Calling sheet as an OLD CSP: nothing is mailed.
    source_sheets.run(w.session)
    assert OLD in w.koda
    _sync()
    assert _new_csps().get("documents_sent", 0) == 0
    assert w.emails == []

    # The verification WhatsApp.
    noon = datetime(2026, 10, 22, 6, 30, tzinfo=timezone.utc)
    assert verify.run_batch(w.session, now=noon)["sent"] == [OLD]
    [ask] = [m for m in w.whatsapp if m["to"].endswith("9000000601")]
    assert _new_csps().get("documents_sent", 0) == 0, "nothing before they answer"

    # They answer (correcting the address); the documents follow.
    token = re.search(r"([A-Za-z0-9_\-]{20,})\s*$", ask["link"]).group(1)
    form = (await client.get(f"/api/csp-form/{token}")).json()
    assert {"ao", "rbo_name"} <= {f["name"] for f in form["fields"]}
    answers = {f["name"]: f["value"] for f in form["fields"]
               if f["type"] != "photo" and f["value"]}
    answers["address"] = "Ward 5, Pakur, Jharkhand 816107"
    r = await client.post(f"/api/csp-form/{token}", json={"values": answers})
    assert r.status_code == 200, r.text
    assert w.koda[OLD]["Address"] == "Ward 5, Pakur, Jharkhand 816107"

    _sync()
    out = _new_csps()
    assert out["documents_sent"] == 1, out
    [mail] = w.emails
    assert mail["to_email"] == "ramesh@example.com" and mail["csp_id"] == OLD
    w.session.expire_all()
    old = w.session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == OLD)).scalars().one()
    assert old.address == "Ward 5, Pakur, Jharkhand 816107"
    assert old.new_csp_processed_at is not None, "never sent twice"
    assert verify.run_batch(w.session, now=noon)["sent"] == [], \
        "not asked again"


async def test_a_csp_already_in_cspdata_gets_nothing_after_answering(
        world, client):
    """A CSP that was in CSPDATA before the import is never enrolled, even
    if it somehow answers a form (No. 128)."""
    from app.routers import csp_form_router
    from app.services import data_request_service as drs
    w = world
    w.session.add(CSPRecord(csp_id="1A955602", csp_code="1A955602",
                            name="Already There", origin="baseline",
                            mobile="9000000602"))
    w.session.commit()
    w.koda["1A955602"] = {"CSP Code": "1A955602"}
    _, token = drs.create(w.session, "1A955602", ["address"])
    w.session.commit()
    r = await client.post(f"/api/csp-form/{token}",
                          json={"values": {"address": "Ward 1, Gaya"}})
    assert r.status_code == 200, r.text
    w.session.expire_all()
    rec = w.session.execute(select(CSPRecord).where(
        CSPRecord.csp_id == "1A955602")).scalars().one()
    assert rec.auto_enrolled_at is None
    assert csp_form_router.VERIFIED_BY  # the marker used when enrolled

