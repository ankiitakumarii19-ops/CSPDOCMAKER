"""
CSP Document Generation & Email Automation Platform — Celery Application

Celery worker configuration for background job processing.
"""

from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "cspdocmaker",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="Asia/Kolkata",
    enable_utc=True,

    # Task behavior
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Result expiration
    result_expires=3600,  # 1 hour

    # All tasks use the default "celery" queue, which is what
    # `celery -A app.celery_app worker` consumes. Dedicated queues can be
    # introduced later together with the matching worker -Q flags.

    # Beat schedule — periodic tasks.
    #
    # Each carries an `expires` just short of its own interval. These are
    # periodic refreshes, not work that must eventually happen: if the
    # worker was down or busy, running a stale copy achieves nothing that
    # the next tick will not do anyway.
    #
    # Without this they accumulate. A worker outage left 255 queued syncs,
    # and clearing that backlog hammered Google Sheets hard enough to cause
    # the connection resets that made things worse still.
    beat_schedule={
        "sync-csp-google-sheet": {
            "task": "workers.sync_csp_data",
            "schedule": settings.csp_sync_interval_minutes * 60,
            "options": {"expires": settings.csp_sync_interval_minutes * 60 - 5},
        },
        "sync-authorization-sheet": {
            "task": "workers.sync_authorization",
            "schedule": settings.google_sheets_sync_interval_minutes * 60,
            "options": {
                "expires": settings.google_sheets_sync_interval_minutes * 60 - 5
            },
        },
        "process-new-csps": {
            "task": "workers.process_new_csps",
            "schedule": (settings.csp_sync_interval_minutes + 2) * 60,
            "options": {
                "expires": (settings.csp_sync_interval_minutes + 2) * 60 - 5
            },
        },
        # RM requests that were waiting for the CSP's details (No. 53).
        "complete-pending-requests": {
            "task": "workers.complete_pending_requests",
            "schedule": (settings.csp_sync_interval_minutes + 2) * 60,
            "options": {
                "expires": (settings.csp_sync_interval_minutes + 2) * 60 - 5
            },
        },
        # The pictures in the CSP sheet's Photo column (No. 102).
        "import-sheet-photos": {
            "task": "workers.import_sheet_photos",
            "schedule": settings.sheet_photo_minutes * 60,
            "options": {"expires": settings.sheet_photo_minutes * 60 - 5},
        },
        # The agents are added below, from the registry.
    },
)


def _agent_schedule() -> dict:
    """One entry per scheduled agent, at the interval that agent declares.

    Built from the registry rather than written out here, so an agent is
    scheduled by being registered and an interval is changed in one place.
    Without this the Agents screen said "Running — every 15 min" about
    agents that nothing was calling.
    """
    from app.services import agent_registry

    entries = {}
    for agent in agent_registry.all_agents():
        if agent.trigger == agent_registry.ON_DEMAND or not agent.every_minutes:
            continue
        seconds = agent.every_minutes * 60
        entries[f"agent-{agent.key}"] = {
            "task": "workers.run_agent",
            "schedule": seconds,
            "args": (agent.key,),
            # A run that is still queued when the next one is due is stale:
            # the agent reads current state, so a backlog of them is noise.
            "options": {"expires": seconds - 5},
        }
    return entries


celery_app.conf.beat_schedule.update(_agent_schedule())

# Register worker modules explicitly. autodiscover_tasks(["app.workers"])
# only looks for an `app.workers.tasks` module, which does not exist, so it
# registered nothing.
celery_app.conf.include = [
    "app.workers.auth_sync_worker",
    "app.workers.csp_sync_worker",
    "app.workers.new_csp_worker",
    "app.workers.pending_request_worker",
    "app.workers.sheet_photo_worker",
    "app.workers.agent_worker",
]


# ---- telemetry for background work (No. 79) ---------------------------------
#
# Every task is one traced run: its own run_id (the Celery task id), a span,
# START -> SUCCESS / FAILED with duration, retries logged with their reason,
# failures with the full traceback. Uncaught crashes are captured by
# telemetry.setup in each worker process.

from celery import signals  # noqa: E402

_open_runs = {}


@signals.worker_process_init.connect
@signals.beat_init.connect
@signals.worker_init.connect
def _telemetry_for_worker(**_):
    from app import telemetry
    telemetry.setup("cspdocmaker-worker", settings.log_level)


@signals.task_prerun.connect
def _task_started(task_id=None, task=None, **_):
    from app import telemetry
    telemetry.setup("cspdocmaker-worker", settings.log_level)
    run_cm = telemetry.run(run_id=task_id)
    run_cm.__enter__()
    op_cm = telemetry.operation(f"task {task.name}", "worker",
                                task=task.name, task_id=task_id,
                                retries=getattr(task.request, "retries", 0))
    op_cm.__enter__()
    _open_runs[task_id] = (run_cm, op_cm)


@signals.task_retry.connect
def _task_retrying(request=None, reason=None, **_):
    import logging
    logging.getLogger("worker").warning(
        "[RETRY] task %s will retry (attempt %s): %s",
        getattr(request, "task", "?"), (getattr(request, "retries", 0) or 0) + 1,
        reason, extra={"event": "retry", "status": "RETRYING"})


@signals.task_postrun.connect
def _task_finished(task_id=None, state=None, retval=None, **_):
    import sys
    entry = _open_runs.pop(task_id, None)
    if not entry:
        return
    run_cm, op_cm = entry
    if state != "SUCCESS" and isinstance(retval, BaseException):
        # FAILURE, or RETRY (retval is the Retry; the reason was logged by
        # _task_retrying) — never recorded as a success.
        op_cm.__exit__(type(retval), retval, retval.__traceback__)
    else:
        op_cm.__exit__(None, None, None)
    run_cm.__exit__(*sys.exc_info())
