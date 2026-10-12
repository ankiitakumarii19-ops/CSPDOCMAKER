"""Permanent document storage in PostgreSQL.

Rule since 12 Oct 2026 (tracker No. 87): only the PDF — what the CSP
receives — is kept, for good; the DOCX is a working file and is discarded. Regenerating a document adds a version rather than replacing one, so the
exact file a CSP was sent stays retrievable.
"""

import os

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.models.enums import DocumentFormat, DocumentType
from app.models.stored_document import StoredDocument
from app.services import document_storage_service as storage

CSP_ID = "STORETEST1"

DOCX_BYTES = b"PK\x03\x04 pretend this is a docx"
PDF_BYTES = b"%PDF-1.4 pretend this is a pdf"


@pytest.fixture
def store_db(migrated_db):
    """Synchronous session against the migrated test database."""
    from sqlalchemy import text
    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    with Session(engine) as session:
        session.execute(text(
            "TRUNCATE stored_documents, csp_records RESTART IDENTITY CASCADE"))
        session.add(CSPRecord(
            csp_id=CSP_ID, csp_code=CSP_ID, name="Store Test",
            email="store@example.com", address="1 Test Street",
        ))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def files(tmp_path):
    docx = tmp_path / "Doc.docx"
    pdf = tmp_path / "Doc.pdf"
    docx.write_bytes(DOCX_BYTES)
    pdf.write_bytes(PDF_BYTES)
    return str(docx), str(pdf)


def test_only_the_pdf_is_stored(store_db, files):
    docx, pdf = files
    storage.store_generated_documents(
        store_db, CSP_ID, [(DocumentType.BCP, docx, pdf)])

    rows = store_db.execute(select(StoredDocument)).scalars().all()
    assert [r.file_format for r in rows] == [DocumentFormat.PDF]


def test_the_working_docx_is_discarded(files):
    docx, pdf = files
    storage.discard_working_files([docx, docx, "/no/such/file.docx"])
    assert not os.path.exists(docx), "the working DOCX should be gone"
    assert os.path.exists(pdf), "the PDF is never touched"


def test_the_bytes_survive_the_round_trip(store_db, files):
    docx, pdf = files
    storage.store_generated_documents(
        store_db, CSP_ID, [(DocumentType.BCP, docx, pdf)])

    stored_pdf = storage.get_document(
        store_db, CSP_ID, DocumentType.BCP, DocumentFormat.PDF)
    assert stored_pdf.file_data == PDF_BYTES
    assert stored_pdf.file_size == len(PDF_BYTES)
    assert stored_pdf.content_type == "application/pdf"


def test_the_checksum_detects_tampering(store_db, files):
    docx, pdf = files
    storage.store_generated_documents(
        store_db, CSP_ID, [(DocumentType.BCP, docx, pdf)])

    row = storage.get_document(
        store_db, CSP_ID, DocumentType.BCP, DocumentFormat.PDF)
    assert storage.verify_integrity(row) is True

    row.file_data = b"%PDF-1.4 something else entirely"
    assert storage.verify_integrity(row) is False


def test_regenerating_adds_a_version_and_keeps_the_old_one(store_db, files, tmp_path):
    docx, pdf = files
    storage.store_generated_documents(
        store_db, CSP_ID, [(DocumentType.BCP, docx, pdf)])

    new_pdf = tmp_path / "Doc2.pdf"
    new_pdf.write_bytes(b"%PDF-1.4 the regenerated one")
    storage.store_generated_documents(
        store_db, CSP_ID, [(DocumentType.BCP, docx, str(new_pdf))])

    versions = store_db.execute(
        select(StoredDocument.version).where(
            StoredDocument.document_type == DocumentType.BCP,
            StoredDocument.file_format == DocumentFormat.PDF,
        ).order_by(StoredDocument.version)
    ).scalars().all()
    assert versions == [1, 2], "the earlier version must not be overwritten"

    # The default fetch returns the newest.
    latest = storage.get_document(
        store_db, CSP_ID, DocumentType.BCP, DocumentFormat.PDF)
    assert latest.file_data == b"%PDF-1.4 the regenerated one"

    # The original is still retrievable by version.
    first = storage.get_document(
        store_db, CSP_ID, DocumentType.BCP, DocumentFormat.PDF, version=1)
    assert first.file_data == PDF_BYTES


def test_each_document_type_versions_independently(store_db, files):
    docx, pdf = files
    storage.store_generated_documents(store_db, CSP_ID, [
        (DocumentType.BCP, docx, pdf),
        (DocumentType.CSP_CERTIFICATE, docx, pdf),
    ])
    storage.store_generated_documents(
        store_db, CSP_ID, [(DocumentType.BCP, docx, pdf)])

    assert storage.latest_version(store_db, CSP_ID, DocumentType.BCP) == 2
    assert storage.latest_version(
        store_db, CSP_ID, DocumentType.CSP_CERTIFICATE) == 1


def test_a_failed_store_saves_nothing(store_db, files):
    """All four documents land together or none do."""
    docx, pdf = files
    with pytest.raises(storage.DocumentStorageError):
        storage.store_generated_documents(store_db, CSP_ID, [
            (DocumentType.BCP, docx, pdf),
            (DocumentType.CSP_CERTIFICATE, docx, "/no/such/file.pdf"),
        ])

    assert store_db.execute(select(StoredDocument)).scalars().all() == []


def test_an_empty_file_is_refused(store_db, tmp_path):
    docx = tmp_path / "empty.docx"
    pdf = tmp_path / "empty.pdf"
    docx.write_bytes(DOCX_BYTES)
    pdf.write_bytes(b"")
    with pytest.raises(storage.DocumentStorageError, match="empty"):
        storage.store_generated_documents(
            store_db, CSP_ID, [(DocumentType.BCP, str(docx), str(pdf))])


def test_writing_back_to_disk_reproduces_the_file(store_db, files, tmp_path):
    docx, pdf = files
    storage.store_generated_documents(
        store_db, CSP_ID, [(DocumentType.BCP, docx, pdf)])

    row = storage.get_document(
        store_db, CSP_ID, DocumentType.BCP, DocumentFormat.PDF)
    out_dir = tmp_path / "out"
    written = storage.write_to_disk(row, str(out_dir))

    with open(written, "rb") as fh:
        assert fh.read() == PDF_BYTES
