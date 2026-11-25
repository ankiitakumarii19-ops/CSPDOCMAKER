"""The RM dashboard and every RM acting on every CSP (No. 234).

  * every RM may act on every CSP in Eko's workspace (the migration sets
    the built-in RM role's "which CSPs" to all) — open, edit, photo, link,
    documents — and "own" stays a choice on Feature access;
  * the dashboard lists every CSP still owed a document, with how many
    times it was contacted, filtered by RM, DC, state and district;
  * a CSP already sent every document, a Sub-KO's BCP and the old CSPs (in
    CSPDATA before the import) are not "left".
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import delete

from app.models import CSPRecord, ProcessingJob
from app.models.email_document import EmailDocument
from app.models.email_job import EmailJob
from app.models.email_message import EmailMessage
from app.models.enums import DocumentType, EmailStatus, JobState, WorkflowType
from app.models.source_sheet import SourceSheetState
from app.models.whatsapp_message import WhatsAppMessage
from app.services import csp_access, feature_access, jwt_service
from app.services import pending_documents as pd
from app.services.rm_resolution import BY_SHEET

pytestmark = pytest.mark.asyncio(loop_scope="session")

RM1, RM2 = "rm.dash.one@eko.co.in", "rm.dash.two@eko.co.in"
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


def _auth(email, role="rm"):
    token = jwt_service.create_access_token(
        {"sub": email, "role": role, "name": email.split("@")[0]})
    return {"Authorization": f"Bearer {token}"}


# ---- the rules, without a database -----------------------------------------

def _rec(csp_id, origin="new", **kw):
    base = dict(csp_id=csp_id, csp_code=csp_id, name=f"CSP {csp_id}",
                mobile="9800000000", rm_name="Asha", dc="Dc One",
                state="Bihar", district="Patna", origin=origin, send_hold=None)
    base.update(kw)
    return SimpleNamespace(**base)


ALL = {d.value for d in DocumentType}


def test_who_is_left_and_who_is_not():
    records = [
        _rec("1A000001"),                                   # nothing sent
        _rec("1A000002"),                                   # all sent
        _rec("1A0000031"),                                  # Sub-KO, all but BCP sent
        _rec("1A000004", origin="baseline"),                # old CSP (CSPDATA)
        _rec("1A000005", origin="baseline"),                # Calling-sheet copy
    ]
    mailed = {"1A000002": set(ALL),
              "1A0000031": ALL - {DocumentType.BCP.value}}
    contacts = {"1A000001": {"whatsapp": 2, "email": 1, "last": NOW}}
    out = pd.build_rows(records, mailed, contacts, imported={"1A000005"})
    ids = [r["csp_id"] for r in out["rows"]]
    assert ids == ["1A000001", "1A000005"]
    assert out["old_not_listed"] == 1
    first = out["rows"][0]
    assert first["contacts"] == 3 and first["whatsapp"] == 2
    assert first["last_contacted"] == NOW.isoformat()
    assert len(first["documents_left"]) == len(ALL)


def test_filters_ignore_case_and_spaces_and_options_follow_other_filters():
    rows = pd.build_rows([
        _rec("A1", state="Bihar", district="Patna", rm_name="Asha"),
        _rec("A2", state="Bihar", district="Gaya", rm_name=" asha "),
        _rec("A3", state="Assam", district="Jorhat", rm_name="Ravi", dc="Dc Two"),
    ], {}, {"A3": {"whatsapp": 3, "email": 0, "last": NOW}}, set())["rows"]
    assert [r["csp_id"] for r in pd.apply(rows, {"rm": "ASHA"})] == ["A1", "A2"]
    assert [r["csp_id"] for r in pd.apply(rows, {"dc": "dc two"})] == ["A3"]
    assert [r["csp_id"] for r in pd.apply(rows, {}, contacted="3+")] == ["A3"]
    assert [r["csp_id"] for r in pd.apply(rows, {}, contacted="never")] == ["A1", "A2"]
    assert [r["csp_id"] for r in pd.apply(rows, {}, q="a2")] == ["A2"]
    opts = pd.options(rows, {"state": "Bihar"})
    assert opts["district"] == ["Gaya", "Patna"], "a state shows only its districts"
    assert opts["state"] == ["Assam", "Bihar"], "a filter's own choices stay open"
    groups = pd.grouped(rows, "rm")
    assert groups[0] == {"name": "Asha", "left": 2, "never": 2, "contacts": 0,
                         "average": 0.0}, "one RM, however the name is typed"
    assert groups[1]["name"] == "Ravi" and groups[1]["average"] == 3.0
    assert pd.options(rows, {})["rm"] == ["Asha", "Ravi"]


def test_bands_sorting_and_bad_values():
    assert [pd.band_of(n) for n in (0, 1, 2, 3, 9)] == [
        "never", "1-2", "1-2", "3+", "3+"]
    rows = [{"name": "b", "contacts": 2, "last_contacted": "2026-11-01"},
            {"name": "a", "contacts": 0, "last_contacted": None},
            {"name": "c", "contacts": 5, "last_contacted": "2026-10-01"}]
    assert [r["name"] for r in pd.sort_rows(rows, "contacts")] == ["a", "b", "c"]
    assert [r["name"] for r in pd.sort_rows(rows, "-contacts")] == ["c", "b", "a"]
    assert [r["name"] for r in pd.sort_rows(rows, "last_contacted")] == ["a", "c", "b"]
    with pytest.raises(ValueError):
        pd.check("contacted", "lots", pd.CONTACT_BANDS)
    assert pd.check("contacted", "", pd.CONTACT_BANDS) == ""


# ---- with the database -----------------------------------------------------

CODES = ("1A770001", "1A770002", "1A770003", "1A770004")


@pytest.fixture
async def world(db):
    for model, col in ((WhatsAppMessage, WhatsAppMessage.csp_id),
                       (EmailMessage, EmailMessage.csp_id),
                       (SourceSheetState, SourceSheetState.csp_code)):
        await db.execute(delete(model).where(col.in_(CODES)))
    common = dict(email="csp@example.com", address="1 Street",
                  rm_resolution=BY_SHEET)
    db.add(CSPRecord(csp_id=CODES[0], csp_code=CODES[0], name="Owned By One",
                     rm_email=RM1, rm_name="Rm One", dc="Dc North",
                     state="Bihar", district="Patna", origin="new", **common))
    db.add(CSPRecord(csp_id=CODES[1], csp_code=CODES[1], name="Owned By Two",
                     rm_email=RM2, rm_name="Rm Two", dc="Dc South",
                     state="Assam", district="Jorhat", origin="new", **common))
    db.add(CSPRecord(csp_id=CODES[2], csp_code=CODES[2], name="All Sent",
                     rm_email=RM2, rm_name="Rm Two", dc="Dc South",
                     state="Assam", district="Jorhat", origin="new", **common))
    db.add(CSPRecord(csp_id=CODES[3], csp_code=CODES[3], name="Old Csp",
                     rm_email=RM1, rm_name="Rm One", dc="Dc North",
                     state="Bihar", district="Patna", origin="baseline",
                     **common))
    job = ProcessingJob(job_id=f"JOB-{uuid.uuid4().hex[:8]}", csp_id=CODES[2],
                        workflow_type=WorkflowType.NEW_CSP,
                        current_state=JobState.EMAIL_SENT)
    db.add(job)
    await db.flush()
    mail = EmailJob(processing_job_id=job.id, recipient="csp@example.com",
                    subject="Your CSP Documents", status=EmailStatus.SENT)
    mail.documents = [EmailDocument(document_type=d) for d in DocumentType]
    db.add(mail)
    for i in range(3):
        db.add(WhatsAppMessage(csp_id=CODES[1], phone="919800000002",
                               kind="data_request", send_status="sent",
                               sent_at=NOW - timedelta(days=i)))
    db.add(WhatsAppMessage(csp_id=CODES[1], phone="919800000002",
                           kind="other", send_status="failed", sent_at=NOW))
    db.add(EmailMessage(csp_id=CODES[1], to_email="csp@example.com",
                        kind="data_request", send_status="sent",
                        track_token=uuid.uuid4().hex, sent_at=NOW))
    await db.commit()
    feature_access.forget()
    yield
    for model, col in ((WhatsAppMessage, WhatsAppMessage.csp_id),
                       (EmailMessage, EmailMessage.csp_id)):
        await db.execute(delete(model).where(col.in_(CODES)))
    await db.commit()


async def test_an_rm_acts_on_another_rms_csp(client, world):
    """The migration: Eko's RMs act on every CSP (No. 234)."""
    user = {"sub": RM1, "role": "rm"}
    assert feature_access.record_scope(user) == "all"
    other = CSPRecord(csp_id="X", rm_email=RM2, rm_resolution=BY_SHEET)
    assert csp_access.can_access(other, user) is True
    r = await client.get("/api/csps/search?q=Owned%20By", headers=_auth(RM1))
    assert r.status_code == 200, r.text
    can = {c["csp_id"]: c["can_act"] for c in r.json()["results"]}
    assert can[CODES[1]] is True, "another RM's CSP is no longer view only"
    r = await client.get(f"/api/csps/{CODES[1]}/verification-links",
                         headers=_auth(RM1))
    assert r.status_code == 200, r.text


async def test_the_dashboard_lists_every_rms_csps_with_contacts(client, world):
    r = await client.get("/api/rm-dashboard/pending", headers=_auth(RM1))
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {c["csp_id"]: c for c in body["csps"] if c["csp_id"] in CODES}
    assert set(rows) == {CODES[0], CODES[1]}, \
        "another RM's CSP is listed; all-sent and old CSPs are not"
    assert rows[CODES[1]]["contacts"] == 4, "3 WhatsApps + 1 email; failed not counted"
    assert rows[CODES[1]]["whatsapp"] == 3 and rows[CODES[1]]["email"] == 1
    assert rows[CODES[0]]["contacts"] == 0
    assert body["old_not_listed"] >= 1
    assert "Rm Two" in body["options"]["rm"] and "Dc North" in body["options"]["dc"]

    for params, want in ((("rm", "Rm Two"),), [CODES[1]]), \
                        ((("dc", "dc north"),), [CODES[0]]), \
                        ((("state", "Assam"), ("district", "Jorhat")), [CODES[1]]), \
                        ((("contacted", "never"), ("state", "Bihar")), [CODES[0]]), \
                        ((("contacted", "3%2B"), ("rm", "Rm Two")), [CODES[1]]):
        q = "&".join(f"{k}={v}" for k, v in params)
        body = (await client.get(f"/api/rm-dashboard/pending?{q}",
                                 headers=_auth(RM1))).json()
        got = [c["csp_id"] for c in body["csps"] if c["csp_id"] in CODES]
        assert got == want, (q, got)

    body = (await client.get("/api/rm-dashboard/pending?group_by=rm&rm=Rm%20Two",
                             headers=_auth(RM2))).json()
    assert body["groups"][0]["name"] == "Rm Two"
    assert body["summary"]["three_plus"] >= 1


async def test_csv_bad_values_and_who_may_open_it(client, world):
    r = await client.get("/api/rm-dashboard/pending.csv?rm=Rm%20Two",
                         headers=_auth(RM1))
    assert r.status_code == 200, r.text
    assert "Times contacted" in r.text and "Owned By Two" in r.text
    assert "Owned By One" not in r.text
    r = await client.get("/api/rm-dashboard/pending?contacted=lots",
                         headers=_auth(RM1))
    assert r.status_code == 400 and "contacted" in r.json()["detail"]
    r = await client.get("/api/rm-dashboard/pending?group_by=x",
                         headers=_auth(RM1))
    assert r.status_code == 400
    assert (await client.get("/api/rm-dashboard/pending")).status_code in (401, 403)
    r = await client.get("/api/rm-dashboard/pending",
                         headers=_auth("admin.dash@eko.co.in", "admin"))
    assert r.status_code == 200
