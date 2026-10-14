"""The Database section and CSP photos in the database (tracker No. 89).

A CSP's complete record — every sheet column, the app's own fields, the
photo and every stored PDF — is visible to the Super Admin only, read-only.
Test data only: invented CSPs and a generated image, no real agents.
"""

import io

import pytest
from PIL import Image
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_photo import CSPPhoto
from app.models.csp_record import CSPRecord
from app.services import csp_photo_store, studio_photo
from tests.conftest import MINIMAL_PDF

pytestmark = pytest.mark.asyncio(loop_scope="session")

CSP_ID = "1A900001"


def _image(colour) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 50), colour).save(out, format="JPEG")
    return out.getvalue()


def _auth(role):
    from app.services import jwt_service
    token = jwt_service.create_access_token({
        "sub": f"{role}@eko.co.in", "email": f"{role}@eko.co.in",
        "role": role, "name": role.title()})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sync_db(migrated_db):
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as session:
        session.execute(text(
            "TRUNCATE stored_documents, csp_records RESTART IDENTITY CASCADE"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def photo_csp(sync_db, tmp_path, monkeypatch):
    """A CSP whose original photo and passport version exist on disk."""
    original = tmp_path / f"{CSP_ID}.jpg"
    original.write_bytes(_image("red"))
    passport = tmp_path / f"{CSP_ID}.white.689x886.abc.png"
    passport.write_bytes(_image("white"))
    monkeypatch.setattr(studio_photo, "cached_for",
                        lambda path: str(passport) if path == str(original) else None)
    csp = CSPRecord(csp_id=CSP_ID, csp_code=CSP_ID, name="Test Person",
                    district="Testdistrict", state="Bihar", gender="Male",
                    photo_url=str(original))
    sync_db.add(csp)
    sync_db.commit()
    return csp, original, passport


# ---- photos are filed in the database ------------------------------------

def test_the_original_and_passport_photos_are_stored(sync_db, photo_csp):
    csp, original, passport = photo_csp
    assert csp_photo_store.capture(sync_db, csp) == ["original", "passport"]
    sync_db.commit()
    rows = {r.kind: r for r in sync_db.execute(select(CSPPhoto)).scalars()}
    assert rows["original"].file_data == original.read_bytes()
    assert rows["passport"].file_data == passport.read_bytes()
    assert rows["original"].content_type == "image/jpeg"


def test_storing_again_is_a_no_op_and_a_new_photo_replaces_the_old(sync_db, photo_csp):
    csp, original, _ = photo_csp
    csp_photo_store.capture(sync_db, csp)
    sync_db.commit()
    assert csp_photo_store.capture(sync_db, csp) == [], "unchanged → nothing to do"
    original.write_bytes(_image("blue"))
    assert csp_photo_store.capture(sync_db, csp) == ["original"]
    sync_db.commit()
    rows = sync_db.execute(select(CSPPhoto).where(CSPPhoto.kind == "original")).scalars().all()
    assert len(rows) == 1 and rows[0].file_data == original.read_bytes()


def test_a_failure_to_file_the_photo_never_breaks_the_caller(sync_db, photo_csp, monkeypatch):
    csp, _, _ = photo_csp

    def broken(*a, **k):
        raise RuntimeError("disk said no")
    monkeypatch.setattr(csp_photo_store, "_upsert", broken)
    assert csp_photo_store.capture(sync_db, csp) == []
    # The session is still usable: the caller's own work can go on.
    csp.name = "Still Fine"
    sync_db.commit()
    assert sync_db.get(CSPRecord, csp.id).name == "Still Fine"


def test_a_csp_without_a_photo_is_simply_skipped(sync_db):
    csp = CSPRecord(csp_id="1A900002", csp_code="1A900002", name="No Photo")
    sync_db.add(csp)
    sync_db.commit()
    assert csp_photo_store.capture(sync_db, csp) == []


# ---- the Database section --------------------------------------------------

@pytest.fixture
def full_record(sync_db, photo_csp):
    from app.models.enums import DocumentFormat, DocumentType
    from app.models.stored_document import StoredDocument
    csp, _, _ = photo_csp
    csp_photo_store.capture(sync_db, csp)
    doc = StoredDocument(
        csp_id=CSP_ID, document_type=DocumentType.CSP_CERTIFICATE,
        file_format=DocumentFormat.PDF, version=1, filename="Appointment.pdf",
        content_type="application/pdf", file_data=MINIMAL_PDF,
        file_size=len(MINIMAL_PDF),
        checksum=__import__("hashlib").sha256(MINIMAL_PDF).hexdigest())
    sync_db.add(doc)
    sync_db.commit()
    return str(doc.id)


# Changed 14 Oct 2026 (No. 104): RMs and Admins see the Database too —
# every CSP, read-only.
@pytest.mark.parametrize("role,expected", [("admin", 200), ("rm", 200)])
async def test_rms_and_admins_see_the_database(client, full_record, role, expected):
    for path in ("/api/admin/database", f"/api/admin/database/{CSP_ID}",
                 f"/api/admin/database/{CSP_ID}/photo/original",
                 f"/api/admin/database/{CSP_ID}/documents/{full_record}"):
        r = await client.get(path, headers=_auth(role))
        assert r.status_code == expected, (role, path, r.status_code)


async def test_nobody_logged_out_sees_it(client, full_record):
    r = await client.get("/api/admin/database")
    assert r.status_code == 401


async def test_the_list_is_searchable_and_shows_photo_and_documents(client, full_record):
    r = await client.get("/api/admin/database?q=testdistrict", headers=_auth("super_admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["csp_id"] == CSP_ID and item["level"] == "KO"
    assert item["photo"] == ["original", "passport"]
    assert item["documents"] == ["Appointment Letter"]
    r = await client.get("/api/admin/database?q=nothing-like-this", headers=_auth("super_admin"))
    assert r.json()["total"] == 0


async def test_the_record_has_every_sheet_column_photo_and_documents(client, full_record):
    r = await client.get(f"/api/admin/database/{CSP_ID}", headers=_auth("super_admin"))
    assert r.status_code == 200, r.text
    rec = r.json()
    from app.routers.database_router import SHEET_COLUMNS
    assert [f["label"] for f in rec["sheet"]] == [label for _, label in SHEET_COLUMNS]
    assert len(rec["sheet"]) == 23
    assert {f["key"] for f in rec["app"]} >= {"status", "origin", "created_at"}
    assert not {"id", "workspace_id"} & {f["key"] for f in rec["app"]}
    assert {p["kind"] for p in rec["photos"]} == {"original", "passport"}
    assert rec["documents"][0]["label"] == "Appointment Letter"
    assert rec["documents"][0]["versions"][0]["id"] == full_record


async def test_the_photo_and_the_pdf_open(client, full_record):
    h = _auth("super_admin")
    r = await client.get(f"/api/admin/database/{CSP_ID}/photo/passport", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/")
    r = await client.get(f"/api/admin/database/{CSP_ID}/documents/{full_record}", headers=h)
    assert r.status_code == 200 and r.content == MINIMAL_PDF
    assert r.headers["content-type"] == "application/pdf"


async def test_unknown_things_are_404(client, full_record):
    h = _auth("super_admin")
    for path in ("/api/admin/database/NOPE", f"/api/admin/database/{CSP_ID}/photo/selfie",
                 f"/api/admin/database/{CSP_ID}/documents/not-a-uuid",
                 "/api/admin/database/NOPE/documents/" + full_record):
        assert (await client.get(path, headers=h)).status_code == 404, path
