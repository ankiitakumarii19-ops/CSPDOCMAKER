"""The daily backup is watched (No. 199, Stage 0): the backup service writes
"ok|failed <unix time> <file or why>"; the alerts tell the Super Admins when
a backup failed, is late, or never ran. Nothing is checked on a laptop."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import alerts

NOW = datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc)


def _settings(path=""):
    return SimpleNamespace(backup_status_file=str(path), backup_alert_hours=26)


def _note(tmp_path, state, hours_ago, rest):
    when = int((NOW - timedelta(hours=hours_ago)).timestamp())
    path = tmp_path / "cspdocmaker-last-backup.txt"
    path.write_text(f"{state} {when} {rest}\n", encoding="utf-8")
    return path


def test_no_backups_here_means_nothing_checked():
    assert alerts.backup_problem(_settings(""), NOW) is None


def test_a_fresh_good_backup_is_fine(tmp_path):
    path = _note(tmp_path, "ok", 3, "cspdocmaker-backup-2026-11-24-0300.dump")
    assert alerts.backup_problem(_settings(path), NOW) is None


def test_a_failed_backup_is_reported_with_why(tmp_path):
    path = _note(tmp_path, "failed", 1, "pg_dump: connection refused")
    p = alerts.backup_problem(_settings(path), NOW)
    assert p.key == "backup" and "failed" in p.title
    assert "connection refused" in p.detail


def test_a_late_backup_is_reported(tmp_path):
    path = _note(tmp_path, "ok", 30, "cspdocmaker-backup-2026-11-23-0000.dump")
    p = alerts.backup_problem(_settings(path), NOW)
    assert p.key == "backup" and "late" in p.title and "30 hours" in p.detail


def test_a_backup_that_never_ran_is_reported(tmp_path):
    p = alerts.backup_problem(_settings(tmp_path / "missing.txt"), NOW)
    assert p.key == "backup" and "No database backup" in p.title


def test_an_unreadable_note_is_reported_not_hidden(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("garbage", encoding="utf-8")
    p = alerts.backup_problem(_settings(path), NOW)
    assert p.key == "backup" and "cannot be read" in p.title
