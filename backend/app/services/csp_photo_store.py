"""
CSP DocMaker — keep each CSP's photo in the database

Decided 12 Oct 2026 (tracker No. 47 / No. 89). The photo pipeline works on
files (csp_photo_service fetches the original, studio_photo makes the
passport version); this module files whatever is current into csp_photos so
the CSP's complete record lives in the database.

capture() is called after any step that may have produced or changed a
photo: the new-CSP worker's fetch, an RM's upload, and document generation
(which makes the passport version). It is idempotent — an unchanged image
(same checksum) is left alone — and it never raises: failing to file a copy
must not fail a delivery, so a problem is logged instead.
"""

import glob
import hashlib
import logging
import mimetypes
import os
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.csp_photo import CSPPhoto, ORIGINAL, PASSPORT

logger = logging.getLogger(__name__)


def original_path(csp) -> Optional[str]:
    """The CSP's original photo file on disk, or None."""
    photo = (getattr(csp, "photo_url", None) or "").strip()
    if photo and os.path.isfile(photo):
        return photo
    from app.services import csp_photo_service
    directory = csp_photo_service.photo_directory()
    for path in sorted(glob.glob(os.path.join(directory, f"{csp.csp_id}.*"))):
        if ".white." not in os.path.basename(path):
            return path
    return None


def _content_type(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _upsert(session: Session, csp_id: str, kind: str, path: str) -> bool:
    with open(path, "rb") as fh:
        data = fh.read()
    if not data:
        return False
    digest = hashlib.sha256(data).hexdigest()
    row = session.execute(
        select(CSPPhoto).where(CSPPhoto.csp_id == csp_id, CSPPhoto.kind == kind)
    ).scalars().first()
    if row is not None and row.checksum == digest:
        return False
    if row is None:
        row = CSPPhoto(csp_id=csp_id, kind=kind)
        session.add(row)
    row.filename = os.path.basename(path)
    row.content_type = _content_type(path)
    row.file_data = data
    row.file_size = len(data)
    row.checksum = digest
    return True


def capture(session: Session, csp) -> List[str]:
    """File the CSP's current original and passport photos. Returns the
    kinds that were added or changed. Flushes, does not commit."""
    from app.services import studio_photo

    changed: List[str] = []
    try:
        # A savepoint: if filing the photo fails, only this is undone — the
        # caller's documents and job in the same transaction are untouched.
        with session.begin_nested():
            original = original_path(csp)
            if original:
                if _upsert(session, csp.csp_id, ORIGINAL, original):
                    changed.append(ORIGINAL)
                passport = studio_photo.cached_for(original)
                if passport and _upsert(session, csp.csp_id, PASSPORT, passport):
                    changed.append(PASSPORT)
    except Exception:
        # Logged with the traceback; the photo files are untouched and the
        # next capture retries.
        logger.warning("csp_photo_store: could not file the photo of CSP %s",
                       getattr(csp, "csp_id", "?"), exc_info=True)
        return []
    if changed:
        logger.info("csp_photo_store: CSP %s — stored %s",
                    csp.csp_id, ", ".join(changed))
    return changed


def photos_for(session: Session, csp_id: str) -> Dict[str, CSPPhoto]:
    rows = session.execute(
        select(CSPPhoto).where(CSPPhoto.csp_id == csp_id)).scalars().all()
    return {r.kind: r for r in rows}
