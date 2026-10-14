"""Every document as a file, one folder per CSP code (tracker No. 105).

The database keeps every PDF; this keeps the same PDFs as files a person can
open on the server: documents/<CSP code>/<Document> v<version>.pdf. Pinned:
where a file goes, that a version is never rewritten, that the folder
catches up on its own, and that a folder the app cannot write to never
fails anything.
"""

import hashlib
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import DocumentFormat, DocumentType
from app.models.stored_document import StoredDocument
from app.services import document_archive

pytestmark = pytest.mark.asyncio(loop_scope="session")

PDF = b"%PDF-1.4 archive test"


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "documents_archive_dir", str(tmp_path / "documents"))
    return tmp_path / "documents"


def test_a_document_goes_in_its_csps_folder(archive):
    path = document_archive.save("1A850395", DocumentType.CSP_ID_CARD, 2, PDF)
    assert path == str(archive / "1A850395" / "CSP ID Card v2.pdf")
    assert open(path, "rb").read() == PDF


def test_a_saved_version_is_never_rewritten(archive):
    path = document_archive.save("1A850395", DocumentType.BCP, 1, PDF)
    os.utime(path, (0, 0))
    document_archive.save("1A850395", DocumentType.BCP, 1, PDF)
    assert os.path.getmtime(path) == 0
    # A new version is a new file; the old one stays.
    document_archive.save("1A850395", DocumentType.BCP, 2, PDF + b"!")
    assert sorted(os.listdir(archive / "1A850395")) == [
        "Business Continuity Plan (BCP) v1.pdf",
        "Business Continuity Plan (BCP) v2.pdf"]


def test_blank_turns_it_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "documents_archive_dir", "")
    assert document_archive.save("1A850395", DocumentType.BCP, 1, PDF) is None


def test_a_folder_that_cannot_be_written_never_fails_anything(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("a file where the folder should be")
    monkeypatch.setattr(get_settings(), "documents_archive_dir", str(blocker))
    assert document_archive.save("1A850395", DocumentType.BCP, 1, PDF) is None
    assert "could not save" in caplog.text


@pytest.fixture
def sync_db(migrated_db):
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    with Session(engine) as session:
        session.execute(text("TRUNCATE stored_documents, csp_records RESTART IDENTITY CASCADE"))
        session.commit()
        yield session
    engine.dispose()


def _stored(session, csp_id, doc_type, version):
    from app.models.csp_record import CSPRecord
    if not session.query(CSPRecord).filter_by(csp_id=csp_id).first():
        session.add(CSPRecord(csp_id=csp_id, name=f"CSP {csp_id}"))
        session.flush()
    session.add(StoredDocument(
        csp_id=csp_id, document_type=doc_type, file_format=DocumentFormat.PDF,
        version=version, filename="x.pdf", content_type="application/pdf",
        file_data=PDF, file_size=len(PDF), checksum=hashlib.sha256(PDF).hexdigest()))
    session.commit()


def test_documents_made_before_are_written_on_the_next_run(sync_db, archive):
    _stored(sync_db, "1A850076", DocumentType.CSP_ID_CARD, 1)
    _stored(sync_db, "1A850076", DocumentType.CSP_CERTIFICATE, 1)
    _stored(sync_db, "1A852458", DocumentType.BCP, 3)
    first = document_archive.export_missing(sync_db)
    assert (first["saved"], first["failed"]) == (3, 0)
    assert sorted(os.listdir(archive)) == ["1A850076", "1A852458"]
    assert os.listdir(archive / "1A852458") == ["Business Continuity Plan (BCP) v3.pdf"]
    again = document_archive.export_missing(sync_db)
    assert again["saved"] == 0, "files already there were written again"
