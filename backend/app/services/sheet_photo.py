"""
CSP DocMaker — show each CSP's photo in the CSP sheet's Photo column

Decided 13 Oct 2026 (tracker No. 91). Whenever the app gets or changes a
CSP's photo, the sheet shows it, automatically:

  1. push() writes  =IMAGE("<private link>")  into the CSP's Photo cell.
     The link is signed, opens only that one photo, and expires after
     LINK_HOURS — long enough for step 2.
  2. A small script installed once in the Google Sheet
     (deploy/sheet-photo-script.gs) turns that formula into a real in-cell
     picture every few minutes; Google keeps its own copy, so the expired
     link no longer matters.

The photo shown is the passport version (35 x 45 mm, as printed on the
documents) once it exists, otherwise the photo as obtained.

Only possible where Google can reach the app (PUBLIC_APP_URL is a public
address); on a laptop it is skipped and says so. Never raises: a sheet that
cannot be updated must not fail a delivery or an upload.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import telemetry

logger = logging.getLogger(__name__)

TOKEN_TYPE = "photo-link"
LINK_HOURS = 24


def link_for(workspace_id, csp_id: str, kind: str, checksum: str) -> str:
    """The private, expiring address of one stored photo."""
    from jose import jwt

    from app.config import get_settings

    s = get_settings()
    claims = {
        "type": TOKEN_TYPE,
        "ws": str(workspace_id),
        "csp": csp_id,
        "kind": kind,
        # A new photo gets a new link; the old one stops working.
        "sum": checksum[:16],
        "exp": datetime.now(timezone.utc) + timedelta(hours=LINK_HOURS),
    }
    token = jwt.encode(claims, s.jwt_secret_key, algorithm=s.jwt_algorithm)
    return f"{s.public_app_url.rstrip('/')}/api/public/photos/{token}"


def read_link(token: str) -> Optional[dict]:
    """The link's claims if it is genuine and unexpired, else None."""
    from app.services import jwt_service
    claims = jwt_service.decode_token(token)
    if not claims or claims.get("type") != TOKEN_TYPE:
        return None
    return claims


def formula_for(url: str) -> str:
    return f'=IMAGE("{url}")'


@telemetry.traced("push_photo_to_sheet", "sheet_photo")
def push(csp_id: str, workspace_id) -> dict:
    """Show this CSP's current photo in the sheet. Returns what happened:
    {"status": "written" | "skipped" | "failed", "reason": str}."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.models.csp_photo import ORIGINAL, PASSPORT
    from app.services import csp_photo_store, message_sender
    from app.services import sheet_writeback_service as wb
    from app.workspace_context import workspace

    settings = get_settings()
    if not message_sender.link_is_reachable(settings.public_app_url):
        return _result("skipped", "the app is not on a public address, so "
                       "Google could not fetch the photo")
    engine = create_engine(settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    try:
        with workspace(workspace_id), Session(engine) as session:
            photos = csp_photo_store.photos_for(session, csp_id)
            photo = photos.get(PASSPORT) or photos.get(ORIGINAL)
            if photo is None:
                return _result("skipped", "no photo stored for this CSP")
            url = link_for(workspace_id, csp_id, photo.kind, photo.checksum)
            kind = photo.kind
        written, skipped = wb.write_values(
            csp_id, {"photo_url": formula_for(url)},
            value_input="USER_ENTERED")
        if not written:
            return _result("skipped", "the sheet has no Photo column")
        logger.info("sheet_photo: CSP %s — %s photo shown in the sheet",
                    csp_id, kind)
        return _result("written", kind)
    except wb.SheetWriteError as e:
        logger.warning("sheet_photo: CSP %s — sheet not updated: %s", csp_id, e)
        return _result("failed", str(e))
    except Exception as e:
        logger.exception("sheet_photo: CSP %s — showing the photo failed", csp_id)
        return _result("failed", f"{type(e).__name__}: {e}")
    finally:
        engine.dispose()


def _result(status: str, reason: str) -> dict:
    if status != "written":
        logger.info("sheet_photo: not shown in the sheet (%s): %s", status, reason)
    return {"status": status, "reason": reason}
