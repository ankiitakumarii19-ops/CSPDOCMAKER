"""
CSP DocMaker — a workspace's logo (No. 240, SaaS upgrade Stage 3)

check_logo(data)  -> the PNG kept: JPEG / PNG / WEBP only (an SVG can carry
                     script, so it is refused), at most 2 MB in, turned
                     upright, at most 600 x 200, transparency kept.
logo_version()    -> the current workspace's logo checksum (short) or None;
                     read for /api/me/access on every page, so it is cached
                     30 s per process and forgotten at once on a change here.
workspace_name()  -> the organisation's name (workspaces.name).
"""

from __future__ import annotations

import io
import logging
import threading
import time
import uuid
from typing import Dict, Optional, Tuple

from app.workspace_context import current_workspace_id

logger = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024
MAX_SIZE = (600, 200)
CACHE_SECONDS = 30

_lock = threading.Lock()
_cache: Dict[uuid.UUID, Tuple[float, Optional[str], str]] = {}
_last_error = 0.0


class LogoError(ValueError):
    """A logo that cannot be used; the message says why."""


def check_logo(data: bytes) -> bytes:
    if not data:
        raise LogoError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise LogoError("The logo is larger than 2 MB. Please use a smaller picture.")
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG", "WEBP"):
                raise LogoError("Please use a PNG, JPEG or WEBP picture.")
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA")
            image.thumbnail(MAX_SIZE, Image.LANCZOS)
            out = io.BytesIO()
            image.save(out, "PNG", optimize=True)
            return out.getvalue()
    except LogoError:
        raise
    except (UnidentifiedImageError, OSError) as e:
        raise LogoError("That file is not a picture that can be read. "
                        "Please use a PNG, JPEG or WEBP.") from e


def forget(workspace_id=None) -> None:
    with _lock:
        if workspace_id is None:
            _cache.clear()
        else:
            _cache.pop(uuid.UUID(str(workspace_id)), None)


def _read(workspace_id: uuid.UUID) -> Optional[Tuple[Optional[str], str]]:
    global _last_error
    import psycopg2
    from app.config import get_settings
    s = get_settings().server
    try:
        conn = psycopg2.connect(
            host=s.database_host, port=s.database_port, user=s.database_user,
            password=s.database_password, dbname=s.database_name,
            connect_timeout=3)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT checksum FROM workspace_files WHERE "
                            "workspace_id = %s AND kind = 'logo'",
                            (str(workspace_id),))
                row = cur.fetchone()
                cur.execute("SELECT name FROM workspaces WHERE id = %s",
                            (str(workspace_id),))
                name = cur.fetchone()
        finally:
            conn.close()
    except Exception as e:
        if time.monotonic() - _last_error > 300:
            _last_error = time.monotonic()
            logger.error("workspace_files: could not read the logo of workspace "
                         "%s (%s: %s) — the app's own logo is shown",
                         workspace_id, type(e).__name__, e)
        return None
    return (row[0][:12] if row else None, name[0] if name else "")


def _get() -> Tuple[Optional[str], str]:
    ws = current_workspace_id()
    if ws is None:
        return None, ""
    with _lock:
        hit = _cache.get(ws)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1], hit[2]
    found = _read(ws)
    if found is None:
        return (hit[1], hit[2]) if hit else (None, "")
    with _lock:
        _cache[ws] = (time.monotonic(), found[0], found[1])
    return found


def logo_version() -> Optional[str]:
    return _get()[0]


def workspace_name() -> str:
    return _get()[1]
