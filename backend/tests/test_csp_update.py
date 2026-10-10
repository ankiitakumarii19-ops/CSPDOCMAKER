"""The RM answering the missing-data question.

An old CSP has no certificate date until an RM supplies one. These tests cover
that path, and the failure that used to hide in it: fields dropped from the
schema were accepted and echoed back as if saved, while nothing persisted.
"""

import pytest
from sqlalchemy import select

from app.models import CSPRecord, User
from app.models.enums import AccountStatus, UserRole
from app.services import jwt_service
from app.services.rm_resolution import BY_SHEET

pytestmark = pytest.mark.asyncio(loop_scope="session")

RM = "rm.owner@eko.co.in"
CSP_ID = "OLDCSP1"


def _auth(email=RM, role=UserRole.RM) -> dict:
    token = jwt_service.create_access_token(
        {"sub": email, "role": role.value, "name": "Owner"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def old_csp(db):
    db.add(User(email=RM, name="Owner", mobile="9876543210", role=UserRole.RM,
                account_status=AccountStatus.ACTIVE, password_hash="x"))
    db.add(CSPRecord(
        csp_id=CSP_ID, csp_code=CSP_ID, name="Old Csp",
        email="old@example.com", address="1 Old Street",
        mobile="9876543210", branch_name="Old Branch", branch_code="0001",
        district="Olddistrict", state="Oldstate",
        rm_email=RM, rm_resolution=BY_SHEET, origin="baseline",
        # The one thing an old CSP is missing: nobody has said when its
        # certificates are being made.
        certificate_date=None,
    ))
    await db.commit()


async def _reload(db) -> CSPRecord:
    db.expire_all()
    return (await db.execute(
        select(CSPRecord).where(CSPRecord.csp_id == CSP_ID))).scalar_one()


async def test_the_rm_can_supply_the_certificate_date(client, db, old_csp):
    """The whole point of the missing-data step for an old CSP."""
    from datetime import date

    r = await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                           json={"certificate_date": "2026-09-24"})
    assert r.status_code == 200, r.text
    assert r.json()["certificate_date"] == "2026-09-24"

    record = await _reload(db)
    assert record.certificate_date == date(2026, 9, 24), "the date was not saved"


async def test_a_dropped_field_is_rejected_not_silently_ignored(client, db, old_csp):
    """This used to return 200 and echo the value while saving nothing."""
    r = await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                           json={"module_name": "ThisColumnWasDropped"})
    assert r.status_code == 422, r.text
    body = str(r.json())
    assert "module_name" in body


async def test_an_unknown_field_is_rejected(client, old_csp):
    r = await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                           json={"not_a_field": "x"})
    assert r.status_code == 422


async def test_a_malformed_date_is_rejected(client, db, old_csp):
    r = await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                           json={"certificate_date": "24-09-2026"})
    assert r.status_code == 422
    assert (await _reload(db)).certificate_date is None


async def test_real_sheet_fields_can_be_corrected(client, db, old_csp):
    r = await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(), json={
        "ao": "Bhagalpur", "asm_name": "Some Asm", "branch_code": "8567",
    })
    assert r.status_code == 200, r.text
    record = await _reload(db)
    assert (record.ao, record.asm_name, record.branch_code) == (
        "Bhagalpur", "Some Asm", "8567")


async def test_values_are_trimmed(client, db, old_csp):
    r = await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                           json={"ao": "  Bhagalpur  "})
    assert r.status_code == 200
    assert (await _reload(db)).ao == "Bhagalpur"


async def test_fields_not_sent_are_left_alone(client, db, old_csp):
    await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                       json={"ao": "Bhagalpur"})
    await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                       json={"certificate_date": "2026-09-24"})
    record = await _reload(db)
    assert record.ao == "Bhagalpur", "an earlier correction was wiped"
    assert record.certificate_date is not None


async def test_an_empty_string_does_not_erase_a_value(client, db, old_csp):
    """A blank box in the form means 'not supplied', not 'delete this'."""
    await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                       json={"ao": "Bhagalpur"})
    r = await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                           json={"ao": "   "})
    assert r.status_code == 200
    assert (await _reload(db)).ao == "Bhagalpur"


async def test_an_empty_body_is_a_clear_error(client, old_csp):
    r = await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(), json={})
    assert r.status_code == 400
    assert "No values provided" in r.json()["detail"]


async def test_the_response_shows_the_real_fields(client, old_csp):
    """The dashboard reads these; retired fields must be gone."""
    r = await client.get(f"/api/csps/{CSP_ID}", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    for field in ("district", "state", "ao", "lho", "dc", "certificate_date",
                  "rm_email", "origin"):
        assert field in body, f"{field} missing from the CSP response"
    for retired in ("module_name", "email_id", "onboarded_date",
                    "onboarding_month", "onboarding_year"):
        assert retired not in body, f"{retired} is still exposed"


async def test_an_admin_cannot_edit(client, old_csp):
    """Admins are monitor-only."""
    r = await client.patch(
        f"/api/csps/{CSP_ID}",
        headers=_auth("admin1@eko.co.in", UserRole.ADMIN),
        json={"certificate_date": "2026-09-24"})
    assert r.status_code == 403


async def test_an_old_csp_is_not_blocked_waiting_for_a_date(client, db, old_csp):
    """The rule changed: a certificate carries the day it is made.

    This used to refuse with 422 until the RM supplied a date. An existing
    CSP is no longer asked when they were onboarded before anything can be
    issued — a document made today is dated today.
    """
    check = await client.post(
        f"/api/documents/check-missing/{CSP_ID}", headers=_auth(),
        json={"document_types": ["training_certificate"]})
    assert check.status_code == 200
    missing = {
        f["field_name"]
        for d in check.json()["documents"] for f in d["missing_fields"]
    }
    assert "certificate_date" not in missing


async def test_a_date_can_still_be_set_deliberately(client, db, old_csp):
    """Overriding remains possible; it is simply no longer required."""
    await client.patch(f"/api/csps/{CSP_ID}", headers=_auth(),
                       json={"certificate_date": "2026-09-24"})

    detail = await client.get(f"/api/csps/{CSP_ID}", headers=_auth())
    assert detail.json()["certificate_date"] == "2026-09-24"
