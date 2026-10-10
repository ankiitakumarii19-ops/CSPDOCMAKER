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


def for_each_workspace(fn):
    """Run this task once per active workspace, inside that workspace.

    The wrapped function keeps its own signature and simply runs with the
    workspace in force, so nothing inside it has to know about any of this.
    """
    @wraps(fn)
    def run(*args, **kwargs):
        from app.workspace_context import workspace

        workspaces = active_workspaces()
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
                    results.append({"workspace": slug,
                                    "result": fn(*args, **kwargs)})
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
