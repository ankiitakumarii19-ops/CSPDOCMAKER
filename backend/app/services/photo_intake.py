"""
CSP DocMaker — one way a CSP's photo comes into the app

Decided 14 Oct 2026 (tracker No. 102). A photo arrives three ways: from the
CSP sheet's Photo column, from an RM's upload, and from the CSP's own form.
Each goes through accept(), so every one of them ends the same way:

  * it becomes the CSP's photo (photo_url);
  * the edited passport version is made (white background, 35 x 45 mm —
    studio_photo), which is the picture every screen shows and every
    document prints;
  * both are filed in the database (csp_photos).

The sheet is updated by the caller afterwards (sheet_photo.push), outside
the database transaction, because it talks to Google.
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def check_image(data: bytes) -> str:
    """The file extension for an uploaded photo, or ValueError saying, in
    words a person can act on, why it cannot be used."""
    import io

    from PIL import Image

    if not data:
        raise ValueError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise ValueError("The photo is larger than 10 MB. Please send a "
                         "smaller one.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            kind = image.format
            image.verify()
    except Exception as e:
        raise ValueError("That file is not a photo the app can read. "
                         "Please send a JPEG or PNG.") from e
    if kind not in ALLOWED_FORMATS:
        raise ValueError(f"{kind} photos are not accepted. Please send a "
                         f"JPEG or PNG.")
    return ALLOWED_FORMATS[kind]


def accept(session, csp, path: str) -> List[str]:
    """Make `path` this CSP's photo. Returns the photo kinds added or
    changed in the database. Flushes, does not commit."""
    from app.services import csp_photo_store, studio_photo

    csp.photo_url = path
    passport = studio_photo.make(path)
    if passport is None:
        # Kept, and said: the original still prints (framed as before),
        # but there is no edited version to show yet.
        logger.warning("photo_intake: CSP %s — no passport version could be "
                       "made from %s", csp.csp_id, path)
    return csp_photo_store.capture(session, csp)


def ensure_passport(session, csp) -> Optional[List[str]]:
    """For a CSP that has a photo but no edited version filed yet: make and
    file it. Returns the kinds changed, or None when there is no photo."""
    from app.services import csp_photo_store, studio_photo

    original = csp_photo_store.original_path(csp)
    if original is None:
        return None
    studio_photo.make(original)
    return csp_photo_store.capture(session, csp)
