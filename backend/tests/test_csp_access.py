"""RM access control, enforced server-side in the query layer.

Confirmed rule: an RM sees the CSPs resolved to them, plus every CSP that is
'unresolved' (which all RMs are alerted about and may act on). Admins monitor
everything read-only.
"""

import pytest
from sqlalchemy import select

from app.models import CSPRecord, ProcessingJob, User
from app.models.enums import AccountStatus, UserRole
from app.services import jwt_service
from app.services.rm_resolution import BY_LHO, BY_SHEET, UNRESOLVED

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(autouse=True)
def _no_libreoffice_needed(stub_pdf_conversion):
    """Every workflow in this module converts PDFs through the stub."""


OWNER = "rm.one@eko.co.in"
OTHER = "rm.two@eko.co.in"


def _auth(email: str, role: UserRole = UserRole.RM) -> dict:
    token = jwt_service.create_access_token(
        {"sub": email, "role": role.value, "name": email.split("@")[0]}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def world(db):
    """Two RMs, an Admin, and three CSPs with different ownership."""
    for email, role in ((OWNER, UserRole.RM), (OTHER, UserRole.RM),
                        ("admin1@eko.co.in", UserRole.ADMIN)):
        db.add(User(email=email, name=email.split("@")[0], mobile="9876543210",
                    role=role, account_status=AccountStatus.ACTIVE, password_hash="x"))
    common = dict(
        csp_code="TC", name="Searchable Csp", email="csp@example.com",
        address="1 Test Street", district="Testdistrict", state="Teststate",
    )
    db.add(CSPRecord(csp_id="OWNED", rm_email=OWNER, rm_resolution=BY_SHEET, **common))
    db.add(CSPRecord(csp_id="OTHERS", rm_email=OTHER, rm_resolution=BY_LHO, **common))
    db.add(CSPRecord(csp_id="UNOWNED", rm_email=None, rm_resolution=UNRESOLVED, **common))
    await db.commit()


async def test_search_returns_own_and_unresolved_only(client, world):
    r = await client.get("/api/csps/search?q=Searchable", headers=_auth(OWNER))
    assert r.status_code == 200, r.text
    assert {c["csp_id"] for c in r.json()["results"]} == {"OWNED", "UNOWNED"}


async def test_search_for_the_other_rm_shows_their_own_and_unresolved(client, world):
    r = await client.get("/api/csps/search?q=Searchable", headers=_auth(OTHER))
    assert {c["csp_id"] for c in r.json()["results"]} == {"OTHERS", "UNOWNED"}


async def test_admin_sees_every_csp(client, world):
    r = await client.get("/api/csps/search?q=Searchable",
                         headers=_auth("admin1@eko.co.in", UserRole.ADMIN))
    assert {c["csp_id"] for c in r.json()["results"]} == {"OWNED", "OTHERS", "UNOWNED"}


@pytest.mark.parametrize("csp_id,expected", [
    ("OWNED", 200), ("UNOWNED", 200), ("OTHERS", 404),
])
async def test_direct_fetch_is_scoped(client, world, csp_id, expected):
    r = await client.get(f"/api/csps/{csp_id}", headers=_auth(OWNER))
    assert r.status_code == expected


async def test_another_rms_csp_is_indistinguishable_from_a_missing_one(client, world):
    existing = await client.get("/api/csps/OTHERS", headers=_auth(OWNER))
    missing = await client.get("/api/csps/NOSUCHCSP", headers=_auth(OWNER))
    assert existing.status_code == missing.status_code == 404
    assert existing.json()["detail"] == missing.json()["detail"].replace(
        "NOSUCHCSP", "OTHERS")


async def test_patch_cannot_edit_another_rms_csp(client, db, world):
    r = await client.patch("/api/csps/OTHERS", headers=_auth(OWNER),
                           json={"address": "Hacked Address"})
    assert r.status_code == 404
    record = (await db.execute(
        select(CSPRecord).where(CSPRecord.csp_id == "OTHERS"))).scalar_one()
    assert record.address == "1 Test Street"


async def test_workflow_refuses_another_rms_csp(client, db, world):
    r = await client.post("/api/workflows/process", headers=_auth(OWNER),
                          json={"csp_id": "OTHERS", "document_types": ["csp_certificate"]})
    assert r.status_code == 404
    # Nothing was started for a CSP this RM may not touch.
    assert (await db.execute(select(ProcessingJob))).scalars().all() == []


async def test_workflow_allows_an_unresolved_csp(client, world):
    r = await client.post("/api/workflows/process", headers=_auth(OWNER),
                          json={"csp_id": "UNOWNED", "document_types": ["csp_certificate"]})
    assert r.status_code == 200, r.text
    assert r.json()["ready_to_send"] is True


async def test_document_endpoints_are_scoped(client, world):
    for path in ("/api/documents/check-missing/OTHERS", "/api/documents/generate/OTHERS"):
        r = await client.post(path, headers=_auth(OWNER),
                              json={"document_types": ["csp_certificate"]})
        assert r.status_code == 404, f"{path} was not scoped"


async def test_unauthenticated_requests_are_rejected(client, world):
    assert (await client.get("/api/csps/search?q=Searchable")).status_code == 401
    assert (await client.get("/api/csps/OWNED")).status_code == 401
