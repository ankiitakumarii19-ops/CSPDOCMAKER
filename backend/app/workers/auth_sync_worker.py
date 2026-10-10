"""
CSP DocMaker — Authorization Sync Worker

Mirrors the authorization Google Sheet (RMs and Admins tabs) into
authorization_records, so RM resolution and access checks do not depend on a
live Google call, and so removing someone from the sheet takes effect here.

A row authorizes a user only while its Status column says Active; any other
value, including blank, is stored as inactive.
"""

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.workers.workspace_runner import for_configured_workspace

logger = logging.getLogger(__name__)


@celery_app.task(
    name="workers.sync_authorization",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
@for_configured_workspace
def sync_authorization(self):
    """Refresh authorization_records from the RMs, Admins and SuperAdmins tabs."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.models.authorization_record import AuthorizationRecord
    from app.models.enums import UserRole
    from app.models.sync_run import SyncRun
    from app.services import google_sheets_service as gs

    settings = get_settings()
    engine = create_engine(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    )

    with Session(engine) as session:
        run = SyncRun(source="authorization", status="running")
        session.add(run)
        session.commit()

        try:
            rows_by_role = {}
            for role, sheet_name in (
                (UserRole.RM, settings.google_sheets_rm_sheet_name),
                (UserRole.ADMIN, settings.google_sheets_admin_sheet_name),
                (UserRole.SUPER_ADMIN,
                 settings.google_sheets_super_admin_sheet_name),
            ):
                rows_by_role[role] = gs._read_sheet_tab(sheet_name)
        except RuntimeError as e:
            run.status = "failed"
            run.error_message = str(e)[:2000]
            run.finished_at = datetime.now(timezone.utc)
            session.commit()
            engine.dispose()
            logger.error("auth_sync_worker: could not read the authorization sheet: %s", e)
            raise self.retry(exc=e)

        created = updated = skipped = total = 0
        seen = set()

        for role, rows in rows_by_role.items():
            if not rows or len(rows) < 2:
                continue
            headers = rows[0]
            for raw in rows[1:]:
                total += 1
                row = {
                    h.strip(): (raw[i].strip() if i < len(raw) else "")
                    for i, h in enumerate(headers)
                }
                email = gs.get_field(row, "Email_id", "Email", "Email Id").lower()
                name = gs.get_field(row, "Name")
                if not email or not name:
                    skipped += 1  # incomplete sheet row
                    continue

                active = gs.is_active(row)
                mobile = gs.get_field(row, "Contact_no", "Mobile", "Phone")
                seen.add((email, role))

                existing = session.execute(
                    select(AuthorizationRecord).where(
                        AuthorizationRecord.email == email,
                        AuthorizationRecord.role == role,
                    )
                ).scalar_one_or_none()

                if existing is None:
                    session.add(AuthorizationRecord(
                        email=email, name=name, mobile=mobile, role=role,
                        active=active, source="google_sheet",
                    ))
                    created += 1
                elif (existing.name, existing.mobile, existing.active) != (name, mobile, active):
                    existing.name, existing.mobile, existing.active = name, mobile, active
                    existing.synchronized_at = datetime.now(timezone.utc)
                    updated += 1

        # Anyone no longer present in a tab loses authorization.
        for record in session.execute(select(AuthorizationRecord)).scalars().all():
            if (record.email, record.role) not in seen and record.active:
                record.active = False
                record.synchronized_at = datetime.now(timezone.utc)
                updated += 1
                logger.info(
                    "auth_sync_worker: %s no longer in the %s tab — deactivated",
                    record.email, record.role.value,
                )

        run.status = "completed"
        run.rows_read = total
        run.created_count = created
        run.updated_count = updated
        run.skipped_count = skipped
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

    engine.dispose()
    logger.info(
        "auth_sync_worker: %d row(s) — %d created, %d updated, %d skipped",
        total, created, updated, skipped,
    )
    return {
        "status": "completed", "rows": total,
        "created": created, "updated": updated, "skipped": skipped,
    }
