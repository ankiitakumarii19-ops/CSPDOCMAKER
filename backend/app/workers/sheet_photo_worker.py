"""
CSP DocMaker — take the photos in the CSP sheet into the app

Decided 14 Oct 2026 (tracker No. 102). Before this, a picture in the sheet's
Photo column was only taken when someone asked for that CSP's ID Card, so
the Database screen showed no photo for CSPs whose picture was right there
in the sheet.

Every SHEET_PHOTO_MINUTES this job:

  * takes the sheet picture for every CSP the app has no photo for, makes
    its passport version and files both (photo_intake.accept), then shows
    the passport version in the sheet (sheet_photo.push, No. 91);
  * makes the passport version for any CSP whose photo has none filed yet.

The sheet is downloaded only when some CSP has no photo, so once every
picture is in, a run costs one database query.
"""

import logging

from app.celery_app import celery_app
from app.workers.workspace_runner import for_each_workspace
from app import telemetry

logger = logging.getLogger(__name__)


@celery_app.task(
    name="workers.import_sheet_photos",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
@for_each_workspace
def import_sheet_photos(self):
    """Take the sheet's photos for the CSPs the app has none for."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings

    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    try:
        with Session(engine) as session:
            return run(session)
    finally:
        engine.dispose()


@telemetry.traced("import_sheet_photos", "sheet_photo_worker")
def run(session) -> dict:
    """The work itself, separate from Celery so it can be tested directly."""
    from sqlalchemy import select

    from app.models.csp_photo import PASSPORT, CSPPhoto
    from app.models.csp_record import CSPRecord
    from app.services import (
        csp_photo_store, photo_intake, sheet_photo, sheet_photo_reader)
    from app.workspace_context import current_workspace_id

    csps = session.execute(
        select(CSPRecord).order_by(CSPRecord.csp_id)).scalars().all()
    without = [c for c in csps if csp_photo_store.original_path(c) is None]
    filed_passport = set(session.execute(
        select(CSPPhoto.csp_id).where(CSPPhoto.kind == PASSPORT)
    ).scalars().all())

    taken, still_missing, edited, failed = [], [], [], []
    if without:
        # One fresh download serves every CSP in this run.
        try:
            sheet_photo_reader.sheet_photos(refresh=True)
        except sheet_photo_reader.SheetPhotoError as e:
            logger.error("sheet_photo_worker: the sheet could not be read; "
                         "%d CSP(s) still without a photo: %s",
                         len(without), e)
            return {"taken": 0, "without_photo": len(without),
                    "edited": 0, "failed": len(without), "error": str(e)}
    for csp in without:
        result = sheet_photo_reader.fetch_photo(csp)
        if not result.ok:
            still_missing.append(csp.csp_id)
            continue
        try:
            photo_intake.accept(session, csp, result.path)
            session.commit()
            taken.append(csp.csp_id)
        except Exception:
            session.rollback()
            failed.append(csp.csp_id)
            logger.exception("sheet_photo_worker: CSP %s — the sheet photo "
                             "could not be filed", csp.csp_id)

    # Photos the app already had, but without the edited version filed.
    for csp in csps:
        if csp.csp_id in filed_passport or csp.csp_id in taken:
            continue
        try:
            changed = photo_intake.ensure_passport(session, csp)
            session.commit()
            if changed:
                edited.append(csp.csp_id)
        except Exception:
            session.rollback()
            failed.append(csp.csp_id)
            logger.exception("sheet_photo_worker: CSP %s — the passport "
                             "version could not be made", csp.csp_id)

    # Shown in the sheet as the passport version (No. 91). Never raises.
    for csp_id in taken + edited:
        sheet_photo.push(csp_id, current_workspace_id())

    logger.info("sheet_photo_worker: %d photo(s) taken from the sheet, %d "
                "edited, %d CSP(s) still without a photo, %d failed",
                len(taken), len(edited), len(still_missing), len(failed))
    return {"taken": len(taken), "edited": len(edited),
            "without_photo": len(still_missing), "failed": len(failed)}


@celery_app.task(
    name="workers.archive_documents",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
@for_each_workspace
def archive_documents(self):
    """Write every stored PDF the documents folder lacks (No. 105)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.services import document_archive

    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://")
    )
    try:
        with Session(engine) as session:
            return document_archive.export_missing(session)
    finally:
        engine.dispose()
