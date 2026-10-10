"""Celery must actually register the scheduled tasks it schedules."""

from app.celery_app import celery_app


def test_scheduled_tasks_are_registered():
    celery_app.loader.import_default_modules()
    registered = set(celery_app.tasks)
    scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert scheduled, "beat schedule is empty"
    assert scheduled <= registered, f"scheduled but unregistered: {scheduled - registered}"


def test_csp_sync_runs_every_configured_interval():
    from app.config import get_settings
    entry = celery_app.conf.beat_schedule["sync-csp-google-sheet"]
    assert entry["schedule"] == get_settings().csp_sync_interval_minutes * 60


def test_no_routes_to_unconsumed_queues():
    # The documented worker consumes only the default queue.
    assert not celery_app.conf.task_routes
