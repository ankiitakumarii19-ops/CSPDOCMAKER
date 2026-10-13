"""CSP photos shown in the CSP sheet (tracker No. 91).

Invented CSPs and generated images only. The Google Sheet itself is never
touched: the write-back is replaced by a recorder.
"""

import io

import pytest
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.services import csp_photo_store, sheet_photo, studio_photo
from tests.conftest import DEFAULT_WORKSPACE_ID

pytestmark = pytest.mark.asyncio(loop_scope="session")

CSP_ID = "1A900101"


def _image(colour, size=(40, 50), fmt="PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format=fmt)
    return out.getvalue()


@pytest.fixture
def sync_db(migrated_db):
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as session:
        session.execute(text("TRUNCATE stored_documents, csp_records RESTART IDENTITY CASCADE"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def stored_photo(sync_db, tmp_path, monkeypatch):
    original = tmp_path / f"{CSP_ID}.png"
    original.write_bytes(_image("red"))
    passport = tmp_path / f"{CSP_ID}.white.689x886.abc.png"
    passport.write_bytes(_image("white"))
    monkeypatch.setattr(studio_photo, "cached_for",
                        lambda p: str(passport) if p == str(original) else None)
    csp = CSPRecord(csp_id=CSP_ID, csp_code=CSP_ID, name="Test Person", photo_url=str(original))
    sync_db.add(csp)
    sync_db.commit()
    csp_photo_store.capture(sync_db, csp)
    sync_db.commit()
    return csp


@pytest.fixture
def public_app(monkeypatch):
    monkeypatch.setattr(get_settings(), "public_app_url", "https://indev.eko.in/csp-docmaker")


@pytest.fixture
def sheet(monkeypatch):
    from app.services import sheet_writeback_service as wb
    calls = []

    def record(code, values, tab=None, value_input="RAW"):
        calls.append((code, values, value_input))
        return dict(values), []
    monkeypatch.setattr(wb, "write_values", record)
    return calls


def test_the_passport_photo_is_written_to_the_sheet_as_an_image_formula(stored_photo, public_app, sheet):
    result = sheet_photo.push(CSP_ID, DEFAULT_WORKSPACE_ID)
    assert result == {"status": "written", "reason": "passport"}
    code, values, mode = sheet[0]
    assert code == CSP_ID and mode == "USER_ENTERED"
    formula = values["photo_url"]
    assert formula.startswith('=IMAGE("https://indev.eko.in/csp-docmaker/api/public/photos/')
    assert formula.endswith('")')


def test_nothing_is_written_while_the_app_is_not_public(stored_photo, sheet):
    # The test settings point at localhost, like a laptop.
    assert sheet_photo.push(CSP_ID, DEFAULT_WORKSPACE_ID)["status"] == "skipped"
    assert sheet == []


def test_a_csp_without_a_photo_is_skipped(sync_db, public_app, sheet):
    sync_db.add(CSPRecord(csp_id="1A900102", csp_code="1A900102", name="No Photo"))
    sync_db.commit()
    assert sheet_photo.push("1A900102", DEFAULT_WORKSPACE_ID)["status"] == "skipped"
    assert sheet == []


def test_a_sheet_failure_is_reported_never_raised(stored_photo, public_app, monkeypatch):
    from app.services import sheet_writeback_service as wb

    def broken(*a, **k):
        raise wb.SheetWriteError("quota exceeded")
    monkeypatch.setattr(wb, "write_values", broken)
    result = sheet_photo.push(CSP_ID, DEFAULT_WORKSPACE_ID)
    assert result["status"] == "failed" and "quota" in result["reason"]


# ---- the private photo link -------------------------------------------------

def _link(public_app_photo_kind="passport"):
    from sqlalchemy import select
    from app.models.csp_photo import CSPPhoto
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as s:
        row = s.execute(select(CSPPhoto).where(CSPPhoto.kind == public_app_photo_kind)).scalar_one()
        url = sheet_photo.link_for(DEFAULT_WORKSPACE_ID, CSP_ID, row.kind, row.checksum)
    engine.dispose()
    return url[url.index("/api/public/photos/"):]


async def test_the_link_opens_the_photo_without_signing_in(client, stored_photo):
    r = await client.get(_link())
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad", ["nonsense", "eyJhbGciOiJIUzI1NiJ9.e30.x"])
async def test_a_wrong_link_is_404(client, stored_photo, bad):
    assert (await client.get(f"/api/public/photos/{bad}")).status_code == 404


async def test_a_documents_link_does_not_open_a_photo(client, stored_photo):
    from app.services import documents_whatsapp
    url = documents_whatsapp.link_for(DEFAULT_WORKSPACE_ID, "00000000-0000-0000-0000-000000000000", CSP_ID)
    token = url.rsplit("/", 1)[1]
    assert (await client.get(f"/api/public/photos/{token}")).status_code == 404


async def test_a_link_to_a_replaced_photo_stops_working(client, stored_photo, sync_db, tmp_path):
    old = _link("original")
    (tmp_path / f"{CSP_ID}.png").write_bytes(_image("blue"))
    csp_photo_store.capture(sync_db, sync_db.get(CSPRecord, stored_photo.id))
    sync_db.commit()
    assert (await client.get(old)).status_code == 404


async def test_a_big_photo_is_shrunk_for_the_sheet(client, sync_db, tmp_path, monkeypatch):
    big = tmp_path / f"{CSP_ID}.jpg"
    big.write_bytes(_image("green", size=(1600, 2400), fmt="JPEG"))
    monkeypatch.setattr(studio_photo, "cached_for", lambda p: None)
    csp = CSPRecord(csp_id=CSP_ID, csp_code=CSP_ID, name="Big Photo", photo_url=str(big))
    sync_db.add(csp)
    sync_db.commit()
    csp_photo_store.capture(sync_db, csp)
    sync_db.commit()
    r = await client.get(_link("original"))
    assert r.status_code == 200
    with Image.open(io.BytesIO(r.content)) as im:
        assert max(im.size) <= 1000


# ---- the sheet's Photo column is no longer read back as a path --------------

def test_the_sync_ignores_the_photo_column():
    from app.workers import csp_sync_worker
    assert "photo_url" in csp_sync_worker._SYNC_EXCLUDED


def test_documents_find_the_stored_photo_when_the_record_has_no_path(stored_photo, tmp_path, monkeypatch):
    from app.services import csp_photo_service, document_service
    monkeypatch.setattr(csp_photo_service, "photo_directory", lambda: str(tmp_path))
    stored_photo.photo_url = None
    assert document_service.resolve_photo(stored_photo) == str(tmp_path / f"{CSP_ID}.png")
