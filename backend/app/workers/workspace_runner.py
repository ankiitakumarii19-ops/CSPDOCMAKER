"""
CSP DocMaker — running a background task for each workspace

A request knows whose it is: somebody signed in. A scheduled task does not.
It wakes on a timer with no user, no token and no workspace — and every
scoped table now requires one.

So a periodic task does not do the work itself. It asks which workspaces
are active and runs the work once inside each, which is also what makes
one customer's slow sheet unable to hide another customer's new rows.

Failing one workspace does not stop the rest. A customer whose sheet is
unreachable should not stop everybody else's documents being issued —
except for a retry, which is not a failure but a request to come back,
and is passed through so retrying keeps working.
"""

import logging
from functools import wraps

from celery.exceptions import Retry

logger = logging.getLogger(__name__)


def active_workspaces():
    """Every workspace the scheduler should work on, oldest first."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.models.workspace import Workspace
    from app.workspace_context import all_workspaces

    engine = create_engine(
        get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"),
        pool_pre_ping=True,
    )
    try:
        with Session(engine) as session, all_workspaces():
            return [
                (row.id, row.slug)
                for row in session.execute(
                    select(Workspace)
                    .where(Workspace.active.is_(True))
                    .order_by(Workspace.created_at)
                ).scalars().all()
            ]
    finally:
        engine.dispose()


# No. 214 (Stage 7): each job's own switch and pace per workspace
# (Settings → Background jobs: job_<key>_on, job_<key>_every).
JOB_KEYS = {
    "sync_csp_data": "sheet_read",
    "sync_authorization": "signin_read",
    "sync_source_sheets": "records_sheets",
    "import_sheet_photos": "sheet_photos",
    "refresh_whatsapp_messages": "delivery_status",
    "answer_csp_replies": "replies",
    "verify_old_csps": "verify",
    "contact_loop": "contact_loop",
    "resend_failed": "resend",
    "fix_info": "info_fix",
    "process_new_csps": "new_records",
}


def _redis():
    import redis
    from app.config import get_settings
    s = get_settings().server
    return redis.Redis(host=s.redis_host, port=s.redis_port, db=0,
                       socket_timeout=2)


def job_skip_reason(fn_name: str, workspace_id) -> str:
    """Why this job does not run now for this workspace ('' = run it).
    Called inside the workspace, so its own settings answer."""
    import time
    from app.config import get_settings
    key = JOB_KEYS.get(fn_name)
    if key is None:
        return ""
    s = get_settings()
    if not getattr(s, f"job_{key}_on"):
        return "switched off for this workspace (Settings → Background jobs)"
    every = int(getattr(s, f"job_{key}_every") or 0)
    if every <= 0:
        return ""
    try:
        last = _redis().get(f"cspdm:job:{workspace_id}:{key}")
    except Exception as e:
        logger.error("workspace_runner: cannot read when %s last ran (%s: %s)"
                     " — running it", key, type(e).__name__, e)
        return ""
    if last and time.time() - float(last) < every * 60:
        return f"not due (every {every} minutes for this workspace)"
    return ""


def mark_ran(fn_name: str, workspace_id) -> None:
    import time
    key = JOB_KEYS.get(fn_name)
    if key is None:
        return
    try:
        _redis().set(f"cspdm:job:{workspace_id}:{key}", str(time.time()),
                     ex=7 * 24 * 3600)
    except Exception as e:
        logger.error("workspace_runner: cannot note that %s ran (%s: %s)",
                     key, type(e).__name__, e)


def connected_workspaces() -> set:
    """Workspaces that connected their own main CSP sheet (No. 210)."""
    from sqlalchemy import create_engine, text

    from app.config import get_settings
    engine = create_engine(
        get_settings().database_url.replace(
            "postgresql+asyncpg://", "postgresql+psycopg2://"),
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as conn:
            return {row[0] for row in conn.execute(text(
                "SELECT workspace_id FROM workspace_settings WHERE key = "
                "'google_sheets_csp_sheet_id' AND value #>> '{}' <> ''"))}
    finally:
        engine.dispose()


def for_each_workspace(fn, *, configured_only=False):
    """Run this task once per active workspace, inside that workspace.

    The wrapped function keeps its own signature and simply runs with the
    workspace in force, so nothing inside it has to know about any of this.
    """
    @wraps(fn)
    def run(*args, **kwargs):
        from app.models.workspace import DEFAULT_SLUG
        from app.workspace_context import workspace

        workspaces = active_workspaces()
        if configured_only:
            # Eko (the server's own sheets) and, since No. 210, every
            # workspace that connected its own main sheet — each reads only
            # its own (connection_catalog: eko_only).
            connected = connected_workspaces()
            workspaces = [w for w in workspaces
                          if w[1] == DEFAULT_SLUG or w[0] in connected]
        if not workspaces:
            logger.warning(
                "%s: there are no active workspaces, so there is nothing to "
                "do", fn.__name__,
            )
            return {"workspaces": 0, "results": []}

        results, failures = [], []
        for workspace_id, slug in workspaces:
            try:
                with workspace(workspace_id):
                    skip = job_skip_reason(fn.__name__, workspace_id)
                    if skip:
                        results.append({"workspace": slug,
                                        "result": {"skipped": skip}})
                        continue
                    results.append({"workspace": slug,
                                    "result": fn(*args, **kwargs)})
                    mark_ran(fn.__name__, workspace_id)
            except Retry:
                # Not a failure — Celery's way of saying "try again later".
                # Swallowing it would silently turn off retrying, so a
                # workspace whose sheet is briefly unreachable would be
                # skipped until the next tick instead of being retried.
                raise
            except Exception as e:
                # One customer's failure is not everyone's.
                logger.error(
                    "%s: failed for workspace %s: %s: %s",
                    fn.__name__, slug, type(e).__name__, e, exc_info=True,
                )
                results.append({"workspace": slug, "error":
                                f"{type(e).__name__}: {e}"})
                failures.append(e)

        if failures:
            # Every workspace got its turn — that is the isolation this
            # wrapper exists for. But the task itself still has to fail, or
            # Celery would treat a total outage as a successful run and
            # never retry it.
            if len(failures) == 1:
                raise failures[0]
            raise RuntimeError(
                f"{len(failures)} of {len(workspaces)} workspaces failed: "
                + "; ".join(f"{type(e).__name__}: {e}" for e in failures)
            )

        return {"workspaces": len(workspaces), "results": results}

    return run


def for_configured_workspace(fn):
    """Run this task for each workspace with sheets: Eko's (the ids in the
    environment) and those that connected their own on Setup → Connections.

    The environment's sheet ids answer only inside Eko's workspace; in any
    other they are blank until it connects its own (No. 210), so a task can
    never copy Eko's CSPs and people into a stranger's workspace.
    """
    return for_each_workspace(fn, configured_only=True)
