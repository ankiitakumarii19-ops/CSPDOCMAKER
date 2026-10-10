"""
CSP DocMaker — Permanent Document Storage

Stores generated documents in PostgreSQL. Both formats are kept: the DOCX that
generation produced and the PDF that was emailed to the CSP.

Storing a document never overwrites an earlier one. Each store allocates the
next version for that CSP and document type, so the exact file a CSP received
can always be produced again, even after the templates change.

Two callers need this: the API (AsyncSession) and the Celery workers (sync
Session). Row building is shared and session-free; only the two small query
functions are written twice, once per session style.
"""

import hashlib
import logging
import os
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.enums import DocumentFormat, DocumentType
from app.models.stored_document import StoredDocument

from app.services import document_registry as registry

logger = logging.getLogger(__name__)

CONTENT_TYPES = {
    DocumentFormat.DOCX: (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    DocumentFormat.PDF: "application/pdf",
}


class DocumentStorageError(Exception):
    """Raised when a document could not be stored or read back."""


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _max_version_query(csp_id: str, doc_type: DocumentType):
    return select(func.max(StoredDocument.version)).where(
        StoredDocument.csp_id == csp_id,
        StoredDocument.document_type == doc_type,
    )


def next_version(session: Session, csp_id: str, doc_type: DocumentType) -> int:
    """The version number the next store for this document should use."""
    current = session.execute(_max_version_query(csp_id, doc_type)).scalar()
    return (current or 0) + 1


async def next_version_async(
    session: AsyncSession, csp_id: str, doc_type: DocumentType
) -> int:
    result = await session.execute(_max_version_query(csp_id, doc_type))
    return (result.scalar() or 0) + 1


def build_row(
    csp_id: str,
    doc_type: DocumentType,
    file_format: DocumentFormat,
    filepath: str,
    version: int,
    processing_job_id=None,
) -> StoredDocument:
    """Read a file from disk and build its row. No session, no I/O to the DB."""
    if not os.path.isfile(filepath):
        raise DocumentStorageError(f"Cannot store: file not found: {filepath}")

    with open(filepath, "rb") as fh:
        data = fh.read()

    if not data:
        raise DocumentStorageError(f"Cannot store an empty file: {filepath}")

    return StoredDocument(
        csp_id=csp_id,
        processing_job_id=processing_job_id,
        document_type=doc_type,
        file_format=file_format,
        version=version,
        filename=os.path.basename(filepath),
        content_type=CONTENT_TYPES[file_format],
        file_data=data,
        file_size=len(data),
        checksum=checksum(data),
    )


def build_pair(
    csp_id: str,
    doc_type: DocumentType,
    docx_path: str,
    pdf_path: str,
    version: int,
    processing_job_id=None,
) -> Tuple[StoredDocument, StoredDocument]:
    """Build the DOCX row and its PDF row, sharing one version number."""
    docx_row = build_row(csp_id, doc_type, DocumentFormat.DOCX,
                         docx_path, version, processing_job_id)
    pdf_row = build_row(csp_id, doc_type, DocumentFormat.PDF,
                        pdf_path, version, processing_job_id)
    logger.info(
        "document_storage_service: prepared %s %s v%d "
        "(docx %d bytes, pdf %d bytes)",
        csp_id, registry.code_of(doc_type), version, docx_row.file_size, pdf_row.file_size,
    )
    return docx_row, pdf_row


def store_generated_documents(
    session: Session,
    csp_id: str,
    pairs: Sequence[Tuple[DocumentType, str, str]],
    processing_job_id=None,
) -> List[StoredDocument]:
    """Store every (doc_type, docx_path, pdf_path) produced by one run.

    Commits once, so a run either stores all of its documents or none of them.
    """
    stored: List[StoredDocument] = []
    try:
        for doc_type, docx_path, pdf_path in pairs:
            version = next_version(session, csp_id, doc_type)
            rows = build_pair(csp_id, doc_type, docx_path, pdf_path,
                              version, processing_job_id)
            session.add_all(rows)
            session.flush()  # so the next version query sees this one
            stored.extend(rows)
        session.commit()
    except Exception:
        session.rollback()
        logger.error(
            "document_storage_service: storing documents for CSP %s failed — "
            "nothing was saved", csp_id, exc_info=True,
        )
        raise

    return stored


async def store_generated_documents_async(
    session: AsyncSession,
    csp_id: str,
    pairs: Sequence[Tuple[DocumentType, str, str]],
    processing_job_id=None,
) -> List[StoredDocument]:
    """Async twin of store_generated_documents.

    Does not commit: the caller owns the surrounding workflow transaction, so
    storage lands or rolls back with the rest of the job.
    """
    stored: List[StoredDocument] = []
    for doc_type, docx_path, pdf_path in pairs:
        version = await next_version_async(session, csp_id, doc_type)
        rows = build_pair(csp_id, doc_type, docx_path, pdf_path,
                          version, processing_job_id)
        session.add_all(rows)
        await session.flush()
        stored.extend(rows)
    return stored


def latest_version(
    session: Session, csp_id: str, doc_type: DocumentType
) -> Optional[int]:
    return session.execute(_max_version_query(csp_id, doc_type)).scalar()


def _document_query(
    csp_id: str,
    doc_type: DocumentType,
    file_format: DocumentFormat,
    version: Optional[int],
):
    query = select(StoredDocument).where(
        StoredDocument.csp_id == csp_id,
        StoredDocument.document_type == doc_type,
        StoredDocument.file_format == file_format,
    )
    if version is None:
        return query.order_by(StoredDocument.version.desc()).limit(1)
    return query.where(StoredDocument.version == version)


def get_document(
    session: Session,
    csp_id: str,
    doc_type: DocumentType,
    file_format: DocumentFormat,
    version: Optional[int] = None,
) -> Optional[StoredDocument]:
    """Fetch one stored document; the newest version unless one is named."""
    return session.execute(
        _document_query(csp_id, doc_type, file_format, version)
    ).scalars().first()


async def get_job_documents_async(
    session: AsyncSession,
    processing_job_id,
    file_format: DocumentFormat,
) -> List[StoredDocument]:
    """Every stored file of one format belonging to a processing job.

    This is what the send step attaches, so a CSP receives exactly the files
    that were generated and validated for that job.
    """
    result = await session.execute(
        select(StoredDocument)
        .where(
            StoredDocument.processing_job_id == processing_job_id,
            StoredDocument.file_format == file_format,
        )
        .order_by(StoredDocument.document_type)
    )
    return list(result.scalars().all())


def verify_integrity(record: StoredDocument) -> bool:
    """Whether the stored bytes still match the checksum written with them."""
    return checksum(record.file_data) == record.checksum


def write_to_disk(record: StoredDocument, directory: str) -> str:
    """Write a stored document back out, e.g. to attach it to an email."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, record.filename)
    with open(path, "wb") as fh:
        fh.write(record.file_data)
    return path
