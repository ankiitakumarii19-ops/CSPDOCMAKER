"""New-CSP automation: alert the RM, or produce and send — never both.

The rule being protected: a document is generated ONLY when every field and
the photograph are present. Anything missing means the RM is asked and the
CSP waits. Nothing goes out with a placeholder face.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.rm_alert import MISSING_DATA, OPEN, RESOLVED, RMAlert
from app.models.stored_document import StoredDocument
from app.services.rm_resolution import BY_SHEET, UNRESOLVED
from app.workers import new_csp_worker

RM = "rm.owner@eko.co.in"


@pytest.fixture(autouse=True)
def photo_is_required(monkeypatch):
    """A missing photo is missing data — the rule this module exists to test.

    Set explicitly rather than inherited from the environment, so the suite
    says the same thing wherever it runs.
    """
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "photo_placeholder_allowed", False)


@pytest.fixture
def db(migrated_db):
    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    with Session(engine) as session:
        session.execute(text(
            "TRUNCATE rm_alerts, stored_documents, csp_records "
            "RESTART IDENTITY CASCADE"))
        session.commit()
        yield session
    engine.dispose()


def make_csp(session, csp_id="NEW1", complete=True, origin="new",
             rm_email=RM, photo=None, processed=None):
    """A new CSP, optionally missing the fields a document needs."""
    record = CSPRecord(
        csp_id=csp_id, csp_code=csp_id, name="New Csp",
        email="newcsp@example.com", origin=origin,
        rm_email=rm_email,
        rm_resolution=BY_SHEET if rm_email else UNRESOLVED,
        photo_url=photo, new_csp_processed_at=processed,
        address="1 New Street" if complete else None,
        mobile="9876543210" if complete else None,
        branch_name="Branch" if complete else None,
        branch_code="0001" if complete else None,
        rbo_name="Rbo" if complete else None,
        # The BCP needs these too.
        ao="Testao" if complete else None,
        asm_name="Test Asm" if complete else None,
        asm_email="asm@example.com" if complete else None,
        asm_contact="9876543211" if complete else None,
        district="Testdistrict", state="Teststate",
    )
    session.add(record)
    session.commit()
    return record


@pytest.fixture
def no_crm(monkeypatch):
    """No CRM photo available — the common case today."""
    from app.services import csp_photo_service
    monkeypatch.setattr(
        csp_photo_service, "fetch_photo",
        lambda csp: csp_photo_service.PhotoResult(
            False, reason=csp_photo_service.NO_RECORD),
    )


@pytest.fixture
def sent(monkeypatch):
    """Capture emails instead of sending them."""
    captured = []
    from app.services import email_service
    monkeypatch.setattr(
        email_service, "send_documents_email",
        lambda **kw: (captured.append(kw), True)[1],
    )
    return captured


def _only_workspace(outcome):
    """Unwrap a per-workspace task result.

    Every periodic task now runs once per active workspace and returns
    {"workspaces": n, "results": [{"workspace": slug, "result": ...}]}.
    These tests have one workspace and care about the work, not the
    wrapper — but they still go through it, so the wrapper stays covered.
    """
    assert outcome["workspaces"] == 1, outcome
    first = outcome["results"][0]
    assert "error" not in first, first["error"]
    return first["result"]


def run():
    return _only_workspace(
        new_csp_worker.process_new_csps.apply().get())


# ---- the RM is asked, and nothing is produced ----------------------------

def test_a_csp_missing_its_photo_is_not_documented(db, no_crm, sent):
    """The whole point: no photo means no document, even if all else is there."""
    make_csp(db, complete=True, photo=None)
    result = run()

    assert result["rm_alerted"] == 1
    assert result["documents_sent"] == 0
    assert db.execute(select(StoredDocument)).scalars().all() == []
    assert sent == [], "a document was emailed without a photo"


def test_the_alert_says_exactly_what_is_needed(db, no_crm, sent):
    make_csp(db, complete=False, photo=None)
    run()

    alert = db.execute(select(RMAlert)).scalar_one()
    assert alert.status == OPEN
    assert alert.kind == MISSING_DATA
    assert alert.rm_email == RM
    fields = {f["field"] for f in alert.details["fields"]}
    assert "photo" in fields
    assert "address" in fields
    # Each field says which documents it is holding up.
    assert all(f["blocks"] for f in alert.details["fields"])


def test_an_unresolved_csp_alerts_every_rm(db, no_crm, sent):
    """No owner means no rm_email, which every RM can see."""
    make_csp(db, rm_email=None, photo=None)
    run()
    assert db.execute(select(RMAlert)).scalar_one().rm_email is None


def test_repeated_runs_do_not_pile_up_alerts(db, no_crm, sent):
    """The worker runs every few minutes; one CSP means one alert."""
    make_csp(db, complete=False, photo=None)
    run(); run(); run()
    assert len(db.execute(select(RMAlert)).scalars().all()) == 1


def test_a_blocked_csp_is_not_marked_processed(db, no_crm, sent):
    """It must be picked up again once the RM supplies the data."""
    make_csp(db, complete=False, photo=None)
    run()
    db.expire_all()
    assert db.execute(select(CSPRecord)).scalar_one().new_csp_processed_at is None


# ---- complete CSPs are documented and sent -------------------------------

def test_a_complete_csp_is_documented_stored_and_sent(db, monkeypatch, sent, tmp_path):
    from app.services import csp_photo_service, document_service
    monkeypatch.setattr(document_service.settings, "document_output_dir",
                        str(tmp_path))

    photo = str(tmp_path / "face.png")
    _write_face(photo)
    monkeypatch.setattr(
        csp_photo_service, "fetch_photo",
        lambda csp: csp_photo_service.PhotoResult(True, path=photo,
                                                  source="kyc.pdf"),
    )
    monkeypatch.setattr("app.services.pdf_service.convert_all", _fake_convert)

    make_csp(db, complete=True)
    result = run()

    assert result["documents_sent"] == 1, result
    assert result["rm_alerted"] == 0

    # Only the PDF is stored, for all four documents (No. 87).
    rows = db.execute(select(StoredDocument)).scalars().all()
    assert len(rows) == 4
    assert {r.file_format.value for r in rows} == {"pdf"}

    # Emailed the PDFs.
    assert len(sent) == 1
    assert all(p.endswith(".pdf") for p in sent[0]["doc_filepaths"])


def test_a_processed_csp_is_never_sent_twice(db, monkeypatch, sent, tmp_path):
    from app.services import csp_photo_service, document_service
    monkeypatch.setattr(document_service.settings, "document_output_dir",
                        str(tmp_path))
    photo = str(tmp_path / "face.png")
    _write_face(photo)
    monkeypatch.setattr(
        csp_photo_service, "fetch_photo",
        lambda csp: csp_photo_service.PhotoResult(True, path=photo, source="k.pdf"))
    monkeypatch.setattr("app.services.pdf_service.convert_all", _fake_convert)

    make_csp(db, complete=True)
    run()
    run()
    run()

    assert len(sent) == 1, "the CSP was emailed more than once"


def test_an_already_processed_csp_is_skipped(db, no_crm, sent):
    make_csp(db, complete=True, processed=datetime.now(timezone.utc))
    assert run()["status"] == "nothing_to_do"


def test_baseline_csps_are_never_auto_processed(db, no_crm, sent):
    """Only CSPs added after the first sync are automated."""
    make_csp(db, origin="baseline", complete=False)
    assert run()["status"] == "nothing_to_do"
    assert db.execute(select(RMAlert)).scalars().all() == []


def test_supplying_the_data_clears_the_alert_and_sends(
    db, monkeypatch, sent, tmp_path
):
    """End to end: blocked, RM fills it in, next run completes it."""
    from app.services import csp_photo_service, document_service
    monkeypatch.setattr(document_service.settings, "document_output_dir",
                        str(tmp_path))
    monkeypatch.setattr(
        csp_photo_service, "fetch_photo",
        lambda csp: csp_photo_service.PhotoResult(
            False, reason=csp_photo_service.NO_RECORD))
    monkeypatch.setattr("app.services.pdf_service.convert_all", _fake_convert)

    csp = make_csp(db, complete=False, photo=None)
    run()
    assert db.execute(select(RMAlert)).scalar_one().status == OPEN

    # The RM supplies what was missing, including the photo.
    photo = str(tmp_path / "face.png")
    _write_face(photo)
    csp.address = "1 New Street"
    csp.mobile = "9876543210"
    csp.branch_name = "Branch"
    csp.branch_code = "0001"
    csp.rbo_name = "Rbo"
    csp.ao = "Testao"
    csp.asm_name = "Test Asm"
    csp.asm_email = "asm@example.com"
    csp.asm_contact = "9876543211"
    csp.photo_url = photo
    db.commit()

    result = run()
    assert result["documents_sent"] == 1, result
    db.expire_all()
    assert db.execute(select(RMAlert)).scalar_one().status == RESOLVED
    assert len(sent) == 1


# ---- helpers -------------------------------------------------------------

def _write_face(path):
    """A passport-shaped image; generation only needs a readable file."""
    import struct
    import zlib

    width, height = 350, 450
    raw = b"".join(b"\x00" + b"\xc8\xb4\xa0" * width for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height,
                                              8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw, 6))
                 + chunk(b"IEND", b""))


def _fake_convert(docx_paths, output_dir=None):
    """Stand in for LibreOffice: the workflow, not the converter, is tested."""
    from pathlib import Path
    from tests.conftest import MINIMAL_PDF

    pairs = []
    for docx_path in docx_paths:
        pdf_path = Path(docx_path).with_suffix(".pdf")
        pdf_path.write_bytes(MINIMAL_PDF)
        pairs.append((docx_path, str(pdf_path)))
    return pairs
