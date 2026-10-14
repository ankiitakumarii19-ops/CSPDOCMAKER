"""Every CSP photo comes in one way and is shown passport-size (No. 102).

A photo arrives from the CSP sheet's Photo column, an RM's upload or the
CSP's own form. Each goes through photo_intake.accept: it becomes the CSP's
photo, the edited passport version is made, and both are kept. Screens show
the passport version. Pinned here:

  * an upload that is not a usable photo is refused, saying why;
  * the sheet job takes the sheet's photo for a CSP without one, edits it,
    and does not download the sheet again once every CSP has a photo;
  * the photo endpoint serves the passport version, only to who may see it;
  * the CSP can send their own photo while their link is open — and the
    page never learns the server's file path.
"""

import io

import pytest
from PIL import Image
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_photo import ORIGINAL, PASSPORT, CSPPhoto
from app.models.csp_record import CSPRecord
from app.services import (
    csp_photo_service, jwt_service, photo_intake, sheet_photo,
    sheet_photo_reader, studio_photo)

pytestmark = pytest.mark.asyncio(loop_scope="session")

RM = "rm.photo@eko.co.in"


def _jpeg(colour="red", size=(60, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def _engine(migrated_db):
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    yield engine
    engine.dispose()


@pytest.fixture
def sync_db(_engine):
    with Session(_engine) as session:
        session.execute(text(
            "TRUNCATE data_requests, rm_alerts, csp_photos, csp_records "
            "RESTART IDENTITY CASCADE"))
        session.commit()
        yield session


@pytest.fixture(autouse=True)
def photos_here(tmp_path, monkeypatch):
    """Photos go to a temporary folder; the passport edit (a face model,
    seconds per photo) is replaced by a quick stand-in that writes where the
    real one would; nothing is pushed to the real sheet."""
    monkeypatch.setattr(csp_photo_service, "photo_directory", lambda: str(tmp_path))

    def fake_make(path):
        done = studio_photo._cache_path(path)
        Image.new("RGB", (35, 45), "white").save(done, "PNG")
        return done
    monkeypatch.setattr(studio_photo, "make", fake_make)
    pushed = []
    monkeypatch.setattr(sheet_photo, "push",
                        lambda csp_id, ws: pushed.append(csp_id) or {"status": "written"})
    return pushed


def _sheet_with(monkeypatch, pictures: dict, codes=()):
    found = sheet_photo_reader.SheetPhotos(
        pictures={code: sheet_photo_reader.SheetPicture(
            data=data, extension=".jpg", tab="KOData", row=n + 2)
            for n, (code, data) in enumerate(pictures.items())},
        ambiguous={}, codes=set(pictures) | set(codes))
    downloads = []

    def sheet_photos(refresh=False):
        if refresh:
            downloads.append(1)
        return found
    monkeypatch.setattr(sheet_photo_reader, "sheet_photos", sheet_photos)
    return downloads


def _kinds(session, csp_id):
    return set(session.execute(select(CSPPhoto.kind).where(
        CSPPhoto.csp_id == csp_id)).scalars().all())


# ---- what an upload must be ---------------------------------------------

def test_a_real_photo_is_accepted():
    assert photo_intake.check_image(_jpeg()) == ".jpg"


@pytest.mark.parametrize("kind, says", [
    ("empty", "empty"),
    ("text", "not a photo"),
    ("huge", "larger than 10 MB"),
])
def test_what_is_not_a_usable_photo_is_refused_saying_why(kind, says):
    data = {"empty": b"", "text": b"not a picture",
            "huge": b"x" * (10 * 1024 * 1024 + 1)}[kind]
    with pytest.raises(ValueError, match=says):
        photo_intake.check_image(data)


# ---- the sheet job ------------------------------------------------------

def test_the_sheet_photo_is_taken_edited_and_kept(sync_db, monkeypatch, photos_here):
    from app.workers import sheet_photo_worker

    sync_db.add(CSPRecord(csp_id="1A910001", name="Sheet Only"))
    sync_db.add(CSPRecord(csp_id="1A910002", name="No Picture"))
    sync_db.commit()
    downloads = _sheet_with(monkeypatch, {"1A910001": _jpeg()}, codes={"1A910002"})

    result = sheet_photo_worker.run(sync_db)
    assert result["taken"] == 1 and result["without_photo"] == 1, result
    assert _kinds(sync_db, "1A910001") == {ORIGINAL, PASSPORT}
    assert _kinds(sync_db, "1A910002") == set()
    assert photos_here == ["1A910001"], "the sheet should show the passport version"
    assert downloads == [1]


def test_once_every_csp_has_a_photo_the_sheet_is_not_downloaded(sync_db, monkeypatch):
    from app.workers import sheet_photo_worker

    sync_db.add(CSPRecord(csp_id="1A910003", name="Has One"))
    sync_db.commit()
    downloads = _sheet_with(monkeypatch, {"1A910003": _jpeg()})
    sheet_photo_worker.run(sync_db)
    assert downloads == [1]
    second = sheet_photo_worker.run(sync_db)
    assert second["taken"] == 0
    assert downloads == [1], "the sheet was downloaded with nothing to take"


def test_a_photo_without_an_edited_version_gets_one(sync_db, tmp_path, monkeypatch):
    """A photo the app had before — from the CRM, say — is edited too, so
    what is shown is passport-size whatever the photo's source."""
    from app.workers import sheet_photo_worker

    old = tmp_path / "1A910004.jpg"
    old.write_bytes(_jpeg("blue"))
    sync_db.add(CSPRecord(csp_id="1A910004", name="From Crm", photo_url=str(old)))
    sync_db.commit()
    _sheet_with(monkeypatch, {})
    result = sheet_photo_worker.run(sync_db)
    assert result["edited"] == 1, result
    assert _kinds(sync_db, "1A910004") == {ORIGINAL, PASSPORT}


# ---- the photo the screens show -----------------------------------------

def _rm_user(sync_db):
    """The RM, added once — the users table outlives each test."""
    from app.models.enums import AccountStatus, UserRole
    from app.models.user import User
    if sync_db.execute(select(User).where(User.email == RM)).first() is None:
        sync_db.add(User(email=RM, name="Rm", mobile="9876543210", role=UserRole.RM,
                         account_status=AccountStatus.ACTIVE, password_hash="x"))


def _auth(email, role):
    token = jwt_service.create_access_token({"sub": email, "role": role, "name": "X"})
    return {"Authorization": f"Bearer {token}"}


async def test_screens_get_the_passport_version(
        client, sync_db, monkeypatch):
    from app.services import csp_access

    _rm_user(sync_db)
    sync_db.add(CSPRecord(csp_id="1A910005", name="Mine"))
    sync_db.add(CSPRecord(csp_id="1A910006", name="Bare"))
    sync_db.commit()
    _sheet_with(monkeypatch, {"1A910005": _jpeg()})
    from app.workers import sheet_photo_worker
    sheet_photo_worker.run(sync_db)

    admin = _auth("admin.photo@eko.co.in", "admin")
    r = await client.get("/api/csps/1A910005/photo", headers=admin)
    assert r.status_code == 200, r.text
    assert r.headers["x-photo-kind"] == PASSPORT
    assert Image.open(io.BytesIO(r.content)).size == (35, 45)

    r = await client.get("/api/csps/1A910006/photo", headers=admin)
    assert r.status_code == 404

    # No. 104: an RM sees every CSP's record, so every CSP's photo too —
    # even one outside their own search scope.
    monkeypatch.setattr(csp_access, "accessible_filter",
                        lambda user: CSPRecord.csp_id == "nobody")
    r = await client.get("/api/csps/1A910005/photo", headers=_auth(RM, "rm"))
    assert r.status_code == 200 and r.headers["x-photo-kind"] == PASSPORT
    r = await client.get("/api/csps/NO-SUCH/photo", headers=_auth(RM, "rm"))
    assert r.status_code == 404


# ---- the CSP's own photo -------------------------------------------------

def _link(sync_db, fields):
    from app.services import data_request_service as drs
    sync_db.add(CSPRecord(csp_id="1A910007", name="Form Csp"))
    sync_db.flush()
    _, token = drs.create(sync_db, "1A910007", fields)
    sync_db.commit()
    return token


async def test_a_csp_can_send_their_photo_and_it_is_edited(client, sync_db):
    token = _link(sync_db, ["photo_url", "gender"])
    form = (await client.get(f"/api/csp-form/{token}")).json()
    photo_field = [f for f in form["fields"] if f["name"] == "photo_url"]
    assert photo_field and photo_field[0]["value"] == ""

    r = await client.post(f"/api/csp-form/{token}/photo",
                          files={"file": ("me.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200, r.text
    sync_db.expire_all()
    assert _kinds(sync_db, "1A910007") == {ORIGINAL, PASSPORT}

    form = (await client.get(f"/api/csp-form/{token}")).json()
    value = [f for f in form["fields"] if f["name"] == "photo_url"][0]["value"]
    assert value == "on file", "the page must not be given the server's path"

    # Text sent back for the photo is ignored, never stored as its path.
    r = await client.post(f"/api/csp-form/{token}",
                          json={"values": {"photo_url": "on file", "gender": "Female"}})
    assert r.status_code == 200, r.text
    sync_db.expire_all()
    record = sync_db.execute(select(CSPRecord).where(
        CSPRecord.csp_id == "1A910007")).scalar_one()
    assert record.photo_url and record.photo_url != "on file"


async def test_the_csp_form_refuses_what_is_not_a_photo(client, sync_db):
    token = _link(sync_db, ["photo_url"])
    r = await client.post(f"/api/csp-form/{token}/photo",
                          files={"file": ("x.jpg", b"not a picture", "image/jpeg")})
    assert r.status_code == 400
    assert "not a photo" in r.json()["detail"]


async def test_a_link_that_does_not_ask_for_a_photo_takes_none(client, sync_db):
    token = _link(sync_db, ["gender"])
    r = await client.post(f"/api/csp-form/{token}/photo",
                          files={"file": ("me.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 400


# ---- an RM's upload -------------------------------------------------------

async def test_an_rm_upload_is_edited_and_a_non_photo_refused(client, sync_db):
    _rm_user(sync_db)
    sync_db.add(CSPRecord(csp_id="1A910008", name="Upload Csp", rm_email=RM))
    sync_db.commit()
    headers = _auth(RM, "rm")

    r = await client.post("/api/documents/upload-photo/1A910008", headers=headers,
                          files={"file": ("x.jpg", b"not a picture", "image/jpeg")})
    assert r.status_code == 400 and "not a photo" in r.json()["detail"]
    assert _kinds(sync_db, "1A910008") == set()

    r = await client.post("/api/documents/upload-photo/1A910008", headers=headers,
                          files={"file": ("me.jpg", _jpeg(), "image/jpeg")})
    assert r.status_code == 200, r.text
    sync_db.expire_all()
    assert _kinds(sync_db, "1A910008") == {ORIGINAL, PASSPORT}
    r = await client.get("/api/csps/1A910008/photo", headers=headers)
    assert r.status_code == 200 and r.headers["x-photo-kind"] == PASSPORT
