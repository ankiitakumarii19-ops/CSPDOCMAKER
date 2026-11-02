# -*- coding: utf-8 -*-
"""Alerts to the Super Admins (No. 173).

Once per problem, again after ALERT_REPEAT_HOURS while it lasts, once when
fixed; only Super Admins; server only, 8 am – 8 pm.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select, text

from app.models.agent import AgentState
from app.models.audit_log import AuditLog
from app.models.enums import UserRole
from app.models.sync_run import SyncRun
from app.models.whatsapp_message import WhatsAppMessage
from app.models.workspace_member import WorkspaceMember
from app.services import alerts
from app.workers import alert_worker
from tests.conftest import DEFAULT_WORKSPACE_ID
from tests.test_field_quality import _engine, qdb  # noqa: F401

NOW = datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)      # 12:00 IST
S = SimpleNamespace(csp_sync_interval_minutes=1,
                    google_sheets_sync_interval_minutes=15,
                    source_sheets_interval_minutes=15,
                    calling_sheet_id="", lead_sheet_id="",
                    alert_repeat_hours=4, alert_agent_failures=3,
                    alert_whatsapp_failures=5)


def _setup(db):
    db.execute(text("TRUNCATE agent_states, whatsapp_messages, workspace_members "
                    "RESTART IDENTITY CASCADE"))
    db.add(WorkspaceMember(workspace_id=DEFAULT_WORKSPACE_ID,
                           email="owner@eko.co.in", role=UserRole.SUPER_ADMIN,
                           active=True))
    db.add(WorkspaceMember(workspace_id=DEFAULT_WORKSPACE_ID,
                           email="rm@eko.co.in", role=UserRole.RM, active=True))
    # The sign-in list read fine, so only what a test breaks is a problem.
    db.add(SyncRun(source="authorization", status="completed",
                   started_at=NOW - timedelta(minutes=2),
                   finished_at=NOW - timedelta(minutes=1)))
    db.commit()


def _csp_sync_fine(db, at=NOW):
    db.add(SyncRun(source="csp", status="completed",
                   started_at=at - timedelta(minutes=1), finished_at=at))
    db.commit()


def _csp_sync_failed(db):
    db.add(SyncRun(source="csp", status="failed", error_message="quota exceeded",
                   started_at=NOW - timedelta(minutes=3),
                   finished_at=NOW - timedelta(minutes=2)))
    db.commit()


class Outbox:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def __call__(self, to, subject, body):
        self.sent.append((to, subject, body))
        return self.ok, "" if self.ok else "SMTP down"


def test_a_failed_sheet_read_is_emailed_to_super_admins_only(qdb):
    _setup(qdb)
    _csp_sync_failed(qdb)
    box = Outbox()
    result = alerts.run(qdb, S, box, now=NOW)
    assert result["sent"] == 1
    assert [to for to, _, _ in box.sent] == ["owner@eko.co.in"]
    subject, body = box.sent[0][1], box.sent[0][2]
    assert "CSP sheet: failed" in subject and "quota exceeded" in body


def test_not_again_until_the_repeat_time_then_once_fixed(qdb):
    _setup(qdb)
    _csp_sync_failed(qdb)
    box = Outbox()
    alerts.run(qdb, S, box, now=NOW)
    alerts.run(qdb, S, box, now=NOW + timedelta(hours=1))
    assert len(box.sent) == 1, "one email per problem, not every run"
    alerts.run(qdb, S, box, now=NOW + timedelta(hours=4, minutes=1))
    assert len(box.sent) == 2, "again after the repeat time"

    later = NOW + timedelta(hours=5)
    _csp_sync_fine(qdb, at=later)
    alerts.run(qdb, S, box, now=later)
    assert box.sent[-1][1].startswith("CSP DocMaker: fixed")
    assert alerts.open_keys(qdb) == []


def test_an_agent_failing_again_and_again(qdb):
    _setup(qdb)
    _csp_sync_fine(qdb)
    qdb.add(AgentState(agent_key="document", enabled=True,
                       consecutive_failures=3, last_summary="Document Agent failed"))
    qdb.commit()
    keys = [p.key for p in alerts.problems(qdb, S, now=NOW)]
    assert keys == ["agent:document"]


def test_whatsapps_failing_more_than_going(qdb):
    _setup(qdb)
    _csp_sync_fine(qdb)
    for i in range(5):
        qdb.add(WhatsAppMessage(phone=f"9812345{600 + i}", kind="other",
                                send_status="failed", sent_at=NOW - timedelta(minutes=5)))
    qdb.add(WhatsAppMessage(phone="9812345699", kind="other", send_status="sent",
                            sent_at=NOW - timedelta(minutes=5)))
    qdb.commit()
    assert [p.key for p in alerts.problems(qdb, S, now=NOW)] == ["whatsapp"]


def test_nothing_wrong_sends_nothing(qdb):
    _setup(qdb)
    _csp_sync_fine(qdb)
    box = Outbox()
    assert alerts.run(qdb, S, box, now=NOW)["sent"] == 0 and box.sent == []


def test_an_alert_that_could_not_be_sent_is_tried_again(qdb):
    _setup(qdb)
    _csp_sync_failed(qdb)
    alerts.run(qdb, S, Outbox(ok=False), now=NOW)
    assert qdb.execute(select(AuditLog).where(
        AuditLog.action == alerts.SENT)).first() is None
    box = Outbox()
    alerts.run(qdb, S, box, now=NOW + timedelta(minutes=15))
    assert len(box.sent) == 1


def test_the_laptop_and_the_night_send_nothing(qdb, monkeypatch):
    from app.config import get_settings
    _setup(qdb)
    _csp_sync_failed(qdb)
    box = Outbox()
    monkeypatch.setattr(get_settings(), "public_app_url", "http://localhost:3000")
    assert "not on a public address" in alert_worker.run_once(qdb, NOW, box)["skipped"]
    monkeypatch.setattr(get_settings(), "public_app_url", "https://indev.eko.in/csp-docmaker")
    night = datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc)   # 22:30 IST
    assert alert_worker.run_once(qdb, night, box)["skipped"] == "outside sending hours"
    monkeypatch.setattr(get_settings(), "alerts_enabled", False)
    assert "off" in alert_worker.run_once(qdb, NOW, box)["skipped"]
    assert box.sent == []
