"""
CSP DocMaker — every document as a file, one folder per CSP

Decided 14 Oct 2026 (tracker No. 105). The database keeps every PDF a CSP
was given (No. 87); this keeps the same PDFs as plain files too, where a
person can open them without the app:

    <DOCUMENTS_ARCHIVE_DIR>/<CSP code>/<Document> v<version>.pdf
    e.g. documents/1A850395/CSP ID Card v2.pdf

On the server DOCUMENTS_ARCHIVE_DIR is the `documents` folder inside the
app's own folder (docker-compose.prod.yml). Blank turns it off.

The folder is a copy, never the record: the database stays the source, a
file is never deleted or overwritten here, and a failure to write one is
logged and never fails a delivery. export_missing() fills in anything the
folder lacks — documents made before this existed, or a write that failed —
and runs on a schedule, so the folder catches up on its own.
"""

import logging
import os
from typing import Iterable, Optional, Tuple

from app.config import get_settings

logger = logging.getLogger(__name__)


def root() -> Optional[str]:
    """The archive folder, or None when it is switched off."""
    directory = (get_settings().documents_archive_dir or "").strip()
    return directory or None


def _safe(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_.()" else "_" for c in name)
    return keep.strip(" .") or "unnamed"


def path_for(csp_id: str, doc_type, version: int) -> Optional[str]:
    """Where this document's file belongs, or None when archiving is off."""
    from app.services.missing_data_service import document_label

    base = root()
    if base is None:
        return None
    return os.path.join(base, _safe(csp_id),
                        f"{_safe(document_label(doc_type))} v{version}.pdf")


def save(csp_id: str, doc_type, version: int, data: bytes) -> Optional[str]:
    """Write one document's PDF to its folder. Never raises; returns the
    path written, or None when off or when it could not be written."""
    path = path_for(csp_id, doc_type, version)
    if path is None:
        return None
    try:
        if os.path.isfile(path) and os.path.getsize(path) == len(data):
            return path         # already there; a version is never rewritten
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = f"{path}.part"
        with open(temporary, "wb") as fh:
            fh.write(data)
        os.replace(temporary, path)
        logger.info("document_archive: saved %s", path)
        return path
    except OSError as e:
        # Logged with the reason (most often: the folder is not writable by
        # the app). The document itself is safe in the database.
        logger.error("document_archive: could not save CSP %s %s v%d to %s: "
                     "%s: %s", csp_id, getattr(doc_type, "value", doc_type),
                     version, path, type(e).__name__, e)
        return None


def save_all(items: Iterable[Tuple[str, object, int, bytes]]) -> int:
    """save() for each (csp_id, doc_type, version, data); how many saved."""
    return sum(1 for item in items if save(*item))


def export_missing(session) -> dict:
    """Write every stored PDF the folder does not have yet (sync Session).

    Reads only the list of documents first; a file's bytes are loaded only
    when it is missing, so a run where nothing is missing is one query.
    """
    from sqlalchemy import select

    from app.models.enums import DocumentFormat
    from app.models.stored_document import StoredDocument

    if root() is None:
        return {"enabled": False}
    rows = session.execute(
        select(StoredDocument.id, StoredDocument.csp_id,
               StoredDocument.document_type, StoredDocument.version,
               StoredDocument.file_size)
        .where(StoredDocument.file_format == DocumentFormat.PDF)
    ).all()
    saved = failed = 0
    for row in rows:
        path = path_for(row.csp_id, row.document_type, row.version)
        if os.path.isfile(path) and os.path.getsize(path) == row.file_size:
            continue
        data = session.execute(select(StoredDocument.file_data).where(
            StoredDocument.id == row.id)).scalar_one()
        if save(row.csp_id, row.document_type, row.version, data):
            saved += 1
        else:
            failed += 1
    if saved or failed:
        logger.info("document_archive: %d document(s) written to %s, %d "
                    "failed", saved, root(), failed)
    return {"enabled": True, "documents": len(rows), "saved": saved,
            "failed": failed}
