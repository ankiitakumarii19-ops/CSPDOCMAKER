"""
CSP DocMaker — the file attached to a message to CSPs (No. 257)

Messaging → Ask CSPs: a person attaches a photo, a video or a file and sends
it, with their words, to the CSPs they chose.

  * What may be attached is what WhatsApp carries: a photo (JPG / PNG, at
    most 5 MB), a video (MP4 / 3GP, at most 16 MB) or a file (PDF, Word,
    Excel, PowerPoint, text; at most 16 MB - the platform's upload limit).
    Anything else is refused with the reason, before anything is sent.
  * On WhatsApp the file is the message's header inside a fixed wording per
    kind ("here is a photo / video / file from ..."). Each wording is its
    own template: Meta approves it once; until then the send says "waiting
    for Meta to approve" and nothing goes out.
  * By email the file is attached to the person's words as typed.
  * The file goes to the WhatsApp platform once (platform_ref), reused for a
    day, then uploaded again.
"""

import hashlib
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from app.models.message_attachment import (DOCUMENT, IMAGE, VIDEO,
                                           MessageAttachment)

logger = logging.getLogger(__name__)

MB = 1024 * 1024
REF_KEPT = timedelta(hours=24)

# extension -> (media kind, content type)
ALLOWED = {
    ".jpg": (IMAGE, "image/jpeg"), ".jpeg": (IMAGE, "image/jpeg"),
    ".png": (IMAGE, "image/png"),
    ".mp4": (VIDEO, "video/mp4"), ".3gp": (VIDEO, "video/3gpp"),
    ".pdf": (DOCUMENT, "application/pdf"),
    ".doc": (DOCUMENT, "application/msword"),
    ".docx": (DOCUMENT, "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"),
    ".xls": (DOCUMENT, "application/vnd.ms-excel"),
    ".xlsx": (DOCUMENT, "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet"),
    ".ppt": (DOCUMENT, "application/vnd.ms-powerpoint"),
    ".pptx": (DOCUMENT, "application/vnd.openxmlformats-officedocument."
                        "presentationml.presentation"),
    ".txt": (DOCUMENT, "text/plain"),
}
LIMIT = {IMAGE: 5 * MB, VIDEO: 16 * MB, DOCUMENT: 16 * MB}
WORD = {IMAGE: "photo", VIDEO: "video", DOCUMENT: "file"}

# The WhatsApp wording per kind (owner's wrapper for a person's message,
# 2 Nov 2026, with the kind named so each is its own template).
WHATSAPP_WORDING = {
    kind: ("Namaste {name}, here is a " + word + " from Eko Bharat Ventures: "
           "{message} Thank you.")
    for kind, word in WORD.items()
}


class AttachmentRefused(ValueError):
    """The file cannot be sent; the message says why, in plain words."""


def check(filename: str, data: bytes) -> Tuple[str, str]:
    """(media kind, content type) for this file, or AttachmentRefused."""
    name = (filename or "").strip()
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED:
        raise AttachmentRefused(
            f"'{name or 'this file'}' cannot be sent. Send a photo (JPG, PNG), "
            "a video (MP4, 3GP) or a file (PDF, Word, Excel, PowerPoint, text).")
    if not data:
        raise AttachmentRefused(f"'{name}' is empty.")
    kind, content_type = ALLOWED[ext]
    if len(data) > LIMIT[kind]:
        raise AttachmentRefused(
            f"'{name}' is {len(data) / MB:.1f} MB; a {WORD[kind]} can be at "
            f"most {LIMIT[kind] // MB} MB on WhatsApp.")
    return kind, content_type


def save(session, filename: str, data: bytes, by: str) -> MessageAttachment:
    """Keep the file for this send. The caller commits."""
    kind, content_type = check(filename, data)
    row = MessageAttachment(
        media_kind=kind, filename=os.path.basename(filename.strip())[:255],
        content_type=content_type, data=data, file_size=len(data),
        checksum=hashlib.sha256(data).hexdigest(), uploaded_by=by or None)
    session.add(row)
    session.flush()
    logger.info("message_attachments.save: %s %s (%d bytes) by %s",
                kind, row.filename, len(data), by)
    return row


def platform_ref(session, row: MessageAttachment, wa) -> str:
    """The platform's handle for the file, uploading it when there is none
    or it is older than a day. Raises wa.WhatsAppPlatformError."""
    now = datetime.now(timezone.utc)
    at = row.platform_ref_at
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if row.platform_ref and at and now - at < REF_KEPT:
        return row.platform_ref
    ext = os.path.splitext(row.filename)[1]
    folder = tempfile.mkdtemp(prefix="attach-")
    path = os.path.join(folder, "file" + ext)
    try:
        with open(path, "wb") as fh:
            fh.write(row.data)
        ref = wa.upload_media(path)
    finally:
        try:
            os.remove(path)
            os.rmdir(folder)
        except OSError as e:
            logger.warning("message_attachments: could not remove %s: %s", path, e)
    row.platform_ref, row.platform_ref_at = ref, now
    session.flush()
    return ref


def get(session, attachment_id: Optional[str]) -> Optional[MessageAttachment]:
    """The attachment in this workspace, or None (unknown / not an id)."""
    import uuid

    from sqlalchemy import select
    try:
        key = uuid.UUID(str(attachment_id))
    except (TypeError, ValueError):
        return None
    return session.execute(select(MessageAttachment).where(
        MessageAttachment.id == key)).scalar_one_or_none()
