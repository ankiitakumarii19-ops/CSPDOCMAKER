# -*- coding: utf-8 -*-
"""The verification agent decides by itself (No. 171): the newest value wins.

The cards it used to raise ("1A850833: CSP Email Id disagrees with what the
CSP submitted") waited for an Accept that changed nothing, and came back
every 30 minutes. Now:

  * written differently (GMAIL.COM / gmail.com, 8474 / 008474,
    "RBO 6 Samastipur" / "RBO 6") is not a difference;
  * the sheet changed after the answer reached it → the sheet's value stays;
  * the answer never reached the sheet and nobody changed the sheet since →
    the answer is written to the sheet (on the server only);
  * every decision is logged once, with the old and new value.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.agent import ACCEPTED, PROPOSED, AgentFinding, AgentRun
from app.models.audit_log import AuditLog
from app.models.csp_record import CSPRecord
from app.models.data_request import DataRequest
from app.services import agent_runner as runner
from app.services import agents as _impl  # noqa: F401  (registers the work)
from app.services import verification_auto as va
from app.workspace_context import workspace
from tests.conftest import DEFAULT_WORKSPACE_ID

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


# ---- the rule, on its own --------------------------------------------------

@pytest.mark.parametrize("field,a,b", [
    ("email", "pradeep.salaiya@GMAIL.COM", "pradeep.salaiya@gmail.com"),
    ("branch_code", "8474", "008474"),
    ("rbo_name", "RBO 6 Samastipur", "RBO 6"),
    ("name", "Ram  Kumar ", "ram kumar"),
    ("mobile", "+91 98765 43210", "9876543210"),
])
def test_written_differently_is_the_same(field, a, b):
    assert va.same(field, a, b)


@pytest.mark.parametrize("field,a,b", [
    ("email", "singhrohit1558@gmail.com", "abhicsc1558@gmail.com"),
    ("rbo_name", "RBO 6", "RBO 7"),
    ("branch_code", "8474", "8475"),
])
def test_a_real_difference_is_one(field, a, b):
    assert not va.same(field, a, b)


def _req(**kw):
    base = dict(id=uuid.uuid4(), csp_id="1A852467", sheet_saved=["email"],
                previous_values={"email": "old@gmail.com"},
                answered_values={}, answered_at=NOW)
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_sheet_changed_after_the_answer_keeps_the_sheet():
    d = va.decide(_req(), "email", "singhrohit1558@gmail.com",
                  "abhicsc1558@gmail.com")
    assert d.kind == va.KEPT_SHEET
    assert (d.before, d.after) == ("abhicsc1558@gmail.com", "abhicsc1558@gmail.com")


def test_an_answer_that_never_reached_the_sheet_is_written():
    d = va.decide(_req(sheet_saved=[]), "email", "new@gmail.com",
                  "old@gmail.com")
    assert d.kind == va.WROTE_ANSWER
    assert (d.before, d.after) == ("old@gmail.com", "new@gmail.com")


def test_an_unsaved_answer_loses_to_a_later_sheet_change():
    d = va.decide(_req(sheet_saved=[]), "email", "new@gmail.com",
                  "someone.fixed.it@gmail.com")
    assert d.kind == va.KEPT_SHEET


def test_only_the_newest_answer_counts():
    old = _req(answered_values={"branch_code": "8474"},
               answered_at=NOW - timedelta(days=2))
    new = _req(answered_values={"branch_code": "8475"}, answered_at=NOW)
    assert va.newest_answers([new, old]) == [(new, "branch_code", "8475")]


# ---- the agent, against the database --------------------------------------

@pytest.fixture(scope="module")
def _engine(migrated_db):
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    yield engine
    engine.dispose()


@pytest.fixture
def db(_engine):
    with Session(_engine) as session:
        session.execute(text(
            "TRUNCATE agent_findings, agent_runs, agent_states, audit_logs, "
            "data_requests, csp_records RESTART IDENTITY CASCADE"))
        session.commit()
        with workspace(DEFAULT_WORKSPACE_ID):
            yield session


def _answered(db, csp_id, field, sent, now_value, reached=True, before=None):
    db.add(CSPRecord(csp_id=csp_id, name="Test CSP", origin="baseline",
                     **{field: now_value}))
    db.add(DataRequest(
        csp_id=csp_id, token_hash=hashlib.sha256(csp_id.encode()).hexdigest(),
        fields=[field], status="answered",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        answered_at=datetime.now(timezone.utc),
        answered_values={field: sent},
        previous_values={field: before if before is not None else now_value},
        sheet_saved=[field] if reached else []))
    db.commit()


def _decisions(db):
    db.expire_all()
    return db.execute(select(AuditLog).where(
        AuditLog.action == va.ACTION)).scalars().all()


def test_the_old_cards_are_closed_and_nothing_waits(db):
    run = AgentRun(agent_key="verification", status="ok", summary="old")
    db.add(run)
    db.flush()
    db.add(AgentFinding(run_id=run.id, agent_key="verification",
                        status=PROPOSED, title="1A850833: CSP Email Id disagrees",
                        proposal={"action": "accept_csp_value"}))
    db.commit()
    _answered(db, "1A850833", "email", "pradeep.salaiya@GMAIL.COM",
              "pradeep.salaiya@gmail.com")

    record = runner.run(db, "verification", force=True)
    assert record.status == "ok", record.error
    db.expire_all()
    cards = db.execute(select(AgentFinding)).scalars().all()
    assert not [c for c in cards if c.status == PROPOSED], "nothing waits"
    old = next(c for c in cards if c.title.startswith("1A850833"))
    assert old.status == ACCEPTED and "automatic" in old.decided_by
    assert _decisions(db) == [], "only a capital-letter difference: no change"


def test_a_newer_sheet_value_is_kept_and_logged_once(db):
    _answered(db, "1A852467", "email", "singhrohit1558@gmail.com",
              "abhicsc1558@gmail.com")
    runner.run(db, "verification", force=True)
    runner.run(db, "verification", force=True)      # no second log line

    [row] = _decisions(db)
    assert row.csp_id == "1A852467"
    m = row.metadata_json
    assert m["decision"] == va.KEPT_SHEET
    assert m["csp_answered"] == "singhrohit1558@gmail.com"
    assert m["old_value"] == m["new_value"] == "abhicsc1558@gmail.com"
    assert row.created_at is not None


def test_an_answer_that_never_reached_the_sheet_is_written_on_the_server(
        db, monkeypatch):
    from app.services import sheet_writeback_service as wb

    written = []
    monkeypatch.setattr(get_settings(), "public_app_url", "https://indev.eko.in/csp-docmaker")
    monkeypatch.setattr(wb, "write_values",
                        lambda code, values, **kw: (written.append((code, values)) or (values, [])))
    _answered(db, "1A900001", "branch_code", "8475", "8474", reached=False)

    runner.run(db, "verification", force=True)
    assert written == [("1A900001", {"branch_code": "8475"})]
    db.expire_all()
    assert db.execute(select(CSPRecord.branch_code).where(
        CSPRecord.csp_id == "1A900001")).scalar() == "8475"
    [row] = _decisions(db)
    assert row.metadata_json["decision"] == va.WROTE_ANSWER
    assert (row.metadata_json["old_value"], row.metadata_json["new_value"]) == ("8474", "8475")


def test_the_laptop_never_writes_to_the_sheet(db, monkeypatch):
    from app.services import sheet_writeback_service as wb

    monkeypatch.setattr(get_settings(), "public_app_url", "http://localhost:3000")
    monkeypatch.setattr(wb, "write_values",
                        lambda *a, **k: pytest.fail("the laptop wrote to the sheet"))
    _answered(db, "1A900002", "branch_code", "8475", "8474", reached=False)
    record = runner.run(db, "verification", force=True)
    assert "left for the server" in record.summary
    assert _decisions(db) == []


def test_a_failed_sheet_write_is_reported_and_tried_again(db, monkeypatch):
    from app.services import sheet_writeback_service as wb

    def broken(*a, **k):
        raise wb.SheetWriteError("quota")

    monkeypatch.setattr(get_settings(), "public_app_url", "https://indev.eko.in/csp-docmaker")
    monkeypatch.setattr(wb, "write_values", broken)
    _answered(db, "1A900003", "branch_code", "8475", "8474", reached=False)
    record = runner.run(db, "verification", force=True)
    assert "1 failed" in record.summary
    assert _decisions(db) == [], "not logged as done: tried again next run"
