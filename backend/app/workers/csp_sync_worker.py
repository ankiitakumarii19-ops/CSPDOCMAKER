"""
CSP DocMaker — CSP Sync Worker

Mirrors the CSP Google Sheet into PostgreSQL every minute.

Confirmed rules:

  * The sheet is the source of truth.
  * Only fields whose cell value actually differs are written, so a sync is a
    no-op when nothing changed.
  * A failure is recorded on the SyncRun and retried on the next run. RMs are
    never shown a sync error.
  * The FIRST successful sync is a baseline: every row it sees is an existing
    CSP (origin 'baseline') and none is auto-processed. Rows appearing after
    that are new CSPs (origin 'new') and are picked up by the new-CSP worker.
  * Each row is resolved to an owning RM (see rm_resolution).
"""

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.workers.workspace_runner import for_configured_workspace

logger = logging.getLogger(__name__)

# Fields the sheet owns. Everything else on the record (certificate_date,
# origin, workflow bookkeeping) is set by the application and never overwritten
# by a sync.
# photo_url: the sheet's Photo column shows a picture the app itself puts
# there (No. 91), so it is never read back as a path.
_SYNC_EXCLUDED = {"csp_id", "photo_url"}

# Fields an EMPTY sheet cell must not clear. The sheet is the source of truth
# wherever it has a value, but a blank cell means "no opinion", not "delete".
# photo_url is filled from the CRM, never from the sheet, so letting the sync
# blank it made the photo be re-downloaded from Zoho on every pass.
_KEEP_IF_SHEET_BLANK = {"photo_url"}


@celery_app.task(
    name="workers.sync_csp_data",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
@for_configured_workspace
def sync_csp_data(self):
    """Sync CSP data from the Google Sheet into the local database."""
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.models.authorization_record import AuthorizationRecord
    from app.models.csp_record import CSPRecord
    from app.models.enums import UserRole
    from app.models.sync_run import SyncRun
    from app.services import csp_mapping, rm_resolution
    from app.services.csp_gsheet_service import read_csp_sheet
    from app.services.info_directory import InfoDirectory

    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    )

    with Session(engine) as session:
        # A baseline run is the first CSP sync that ever completed.
        previous_ok = session.execute(
            select(func.count()).select_from(SyncRun).where(
                SyncRun.source == "csp", SyncRun.status == "completed",
            )
        ).scalar() or 0
        is_baseline = previous_ok == 0

        run = SyncRun(source="csp", status="running", is_baseline=is_baseline)
        session.add(run)
        session.commit()

        try:
            rows = read_csp_sheet()
        except RuntimeError as e:
            run.status = "failed"
            run.error_message = str(e)[:2000]
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
            engine.dispose()
            logger.error("csp_sync_worker: could not read the CSP sheet: %s", e)
            raise self.retry(exc=e)

        mapped_rows = [csp_mapping.map_sheet_row(row) for row in rows]

        # The INFO tab says who covers which LHO, State and District. Blank
        # DC / ASM / RM cells are filled from it here, inside the sync, rather
        # than written separately afterwards: the sync compares every field
        # against the sheet each minute, so a value written outside it would
        # be wiped on the next run. Filling here makes the result stable —
        # the same row produces the same record every time.
        info = None
        try:
            info = InfoDirectory.load()
        except Exception as e:
            # Enrichment is optional; losing it must not stop the sync.
            logger.warning(
                "csp_sync_worker: INFO directory unavailable, continuing "
                "without it: %s: %s", type(e).__name__, e,
            )

        enriched = 0
        if info is not None:
            for mapped in mapped_rows:
                supplied = info.fill_missing(mapped)
                if supplied:
                    mapped.update(supplied)
                    enriched += 1

        # RM resolution inputs: authorized RM names, and the LHO → RM map
        # learned from rows that do name an RM.
        rm_records = session.execute(
            select(AuthorizationRecord).where(
                AuthorizationRecord.role == UserRole.RM,
                AuthorizationRecord.active.is_(True),
            )
        ).scalars().all()
        name_to_email = rm_resolution.build_name_to_email(rm_records)
        lho_to_name = rm_resolution.build_lho_to_name(mapped_rows)

        created = updated = skipped = 0
        now = datetime.now(timezone.utc)

        for mapped in mapped_rows:
            csp_id = csp_mapping.csp_id_from_row(mapped)
            if not csp_id:
                skipped += 1  # a row without a CSP Code cannot be identified
                continue

            rm_email, how = rm_resolution.resolve_rm(
                mapped, name_to_email, lho_to_name,
                info=info, authorized_emails=set(name_to_email.values()),
            )

            # Record who INFO says covers this territory when the sheet's RM
            # cell is blank. Done after resolution, never before: resolve_rm
            # reads a populated rm_name as "the sheet named this person" and
            # matches it by name, which the two sheets spell differently.
            if not (mapped.get("rm_name") or "").strip():
                person, _ = rm_resolution.info_rm(mapped, info)
                if person is not None and person.name:
                    mapped["rm_name"] = person.name

            existing = session.execute(
                select(CSPRecord).where(CSPRecord.csp_id == csp_id)
            ).scalar_one_or_none()

            if existing is None:
                # A row the Calling / Lead raw data job added (No. 121) says
                # itself whether it is old or new, and whether it is on hold:
                # an old CSP copied into KOData must never be mailed as new.
                from app.services import source_sheets
                origin, hold = source_sheets.state_for_new_record(
                    session, csp_id)
                record = CSPRecord(
                    csp_id=csp_id,
                    source_row_identifier=csp_id,
                    source_last_updated=now,
                    origin=origin or ("baseline" if is_baseline else "new"),
                    send_hold=hold,
                    rm_email=rm_email,
                    rm_resolution=how,
                    **{k: v for k, v in mapped.items() if k not in _SYNC_EXCLUDED and v},
                )
                session.add(record)
                created += 1
                if record.origin == "new":
                    logger.info("csp_sync_worker: new CSP detected: %s", csp_id)
                continue

            # Field-level diff — only changed cells are written.
            changed = False
            for field, value in mapped.items():
                if field in _SYNC_EXCLUDED:
                    continue
                if (not value and field in _KEEP_IF_SHEET_BLANK
                        and getattr(existing, field, None)):
                    continue   # keep what we already have
                if (getattr(existing, field, None) or "") != value:
                    setattr(existing, field, value or None)
                    changed = True
            if (existing.rm_email or "") != (rm_email or "") or existing.rm_resolution != how:
                existing.rm_email, existing.rm_resolution = rm_email, how
                changed = True
            if changed:
                existing.source_last_updated = now
                updated += 1

        run.status = "completed"
        run.rows_read = len(rows)
        run.created_count = created
        run.updated_count = updated
        run.skipped_count = skipped
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

    engine.dispose()

    summary = {
        "status": "completed",
        "baseline": is_baseline,
        "total_rows": len(rows),
        "new_csps": 0 if is_baseline else created,
        "existing_csps_imported": created if is_baseline else 0,
        "updated_csps": updated,
        "skipped_rows": skipped,
        "rows_enriched_from_info": enriched,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        "csp_sync_worker: %s sync — %d row(s), %d created, %d updated, "
        "%d skipped, %d filled from INFO",
        "baseline" if is_baseline else "incremental",
        len(rows), created, updated, skipped, enriched,
    )
    return summary
