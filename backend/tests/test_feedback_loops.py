"""The feedback loops (No. 150).

Loop 1: repeated corrections to an INFO value become a suggestion; accept /
dismiss; fixed once INFO gives the right value. Loop 2: a bad WhatsApp
number or a bounced email — the CSP is asked on the other channel, once, and
what failed is sent again when it is corrected. Sending is a stand-in:
nothing leaves the test.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.models.csp_record import CSPRecord
from app.models.feedback_loop import ContactFix, QualitySuggestion
from app.services import feedback_loops as fl
from app.services import field_quality as fq
from tests.test_field_quality import _auth, _engine, _filled, qdb  # noqa: F401

on_loop = pytest.mark.asyncio(loop_scope="session")

RULE = "INFO AO block, by branch 'VISARWADI'"


@pytest.fixture
def ldb(qdb):
    qdb.execute(text("TRUNCATE quality_suggestions, contact_fixes, "
                     "whatsapp_messages, email_messages RESTART IDENTITY CASCADE"))
    qdb.commit()
    return qdb


def _info_fill(db, code, value="AO NASHIK", rule=RULE):
    known = fq.load(db, [code])
    fq.record_fill(db, code, "ao", value, "info", rule, known=known)
    db.commit()


def _correct(db, code, to="AO DHULE"):
    fq.record_check(db, code, {"ao": to}, "csp_form", "CSP")
    db.commit()


# ---- loop 1 -------------------------------------------------------------

def test_one_correction_is_not_a_pattern(ldb):
    _info_fill(ldb, "1A995001")
    _correct(ldb, "1A995001")
    assert fl.refresh_suggestions(ldb, 2)["added"] == 0


def test_the_same_correction_on_two_csps_is_a_suggestion(ldb):
    for code in ("1A995001", "1A995002", "1A995003"):
        _info_fill(ldb, code)
    _correct(ldb, "1A995001")
    _correct(ldb, "1A995002")
    _correct(ldb, "1A995003", to="AO PUNE")        # a different fix: not grouped
    assert fl.refresh_suggestions(ldb, 2) == {"added": 1, "fixed": 0}
    ldb.commit()
    assert fl.refresh_suggestions(ldb, 2)["added"] == 0, "not twice"
    _info_fill(ldb, "1A995004")                     # INFO still gives it here
    (s,) = fl.list_suggestions(ldb)
    assert (s["field"], s["rule"], s["from_value"], s["to_value"]) == (
        "ao", RULE, "AO NASHIK", "AO DHULE")
    assert [c["csp_id"] for c in s["csps"]] == ["1A995001", "1A995002"]
    assert (s["status"], s["still_wrong"]) == ("open", 1)


def test_an_accepted_suggestion_is_fixed_when_info_gives_the_right_value(ldb):
    for code in ("1A995001", "1A995002"):
        _info_fill(ldb, code)
        _correct(ldb, code)
    fl.refresh_suggestions(ldb, 2)
    ldb.commit()
    s = ldb.execute(select(QualitySuggestion)).scalar_one()
    fl.decide(ldb, s.id, "accept", "admin@eko.co.in")
    ldb.commit()
    assert fl.refresh_suggestions(ldb, 2)["fixed"] == 0, "INFO not fixed yet"
    _info_fill(ldb, "1A995009", value="AO DHULE")   # the team fixed INFO
    assert fl.refresh_suggestions(ldb, 2)["fixed"] == 1
    ldb.commit()
    assert fl.list_suggestions(ldb)[0]["status"] == "fixed"


@on_loop
async def test_suggestions_are_for_admins_and_decisions_are_audited(client, ldb):
    for code in ("1A995001", "1A995002"):
        _info_fill(ldb, code)
        _correct(ldb, code)
    r = await client.get("/api/admin/quality/suggestions", headers=_auth("rm"))
    assert r.status_code == 403
    r = await client.get("/api/admin/quality/suggestions", headers=_auth("admin"))
    assert r.status_code == 200, r.text
    (s,) = r.json()["suggestions"]
    r = await client.post(f"/api/admin/quality/suggestions/{s['id']}/dismiss",
                          headers=_auth("admin"))
    assert r.json()["status"] == "dismissed"
    r = await client.post(f"/api/admin/quality/suggestions/{s['id']}/delete",
                          headers=_auth("admin"))
    assert r.status_code == 400
    from app.models.audit_log import AuditLog
    ldb.expire_all()
    assert ldb.execute(select(AuditLog.action).where(
        AuditLog.action.like("info_suggestion_%"))).scalars().all() == [
        "info_suggestion_dismiss"]


# ---- loop 2 -------------------------------------------------------------

PHONE = "919812345601"
NOW = datetime.now(timezone.utc)
SETTINGS = SimpleNamespace(contact_loop_batch=10)


def _csp(db, code="1A996001", **kw):
    values = dict(csp_id=code, csp_code=code, name="Loop Csp",
                  mobile="9812345601", email="loop@example.com")
    values.update(kw)
    db.add(CSPRecord(**values))
    db.commit()


def _whatsapp(db, code="1A996001", delivery="failed", kind="data_request",
              when=None):
    from app.models.whatsapp_message import WhatsAppMessage
    db.add(WhatsAppMessage(csp_id=code, phone=PHONE, kind=kind, source="t",
                           send_status="sent", delivery_status=delivery,
                           sent_at=when or NOW - timedelta(hours=2)))
    db.commit()


def _bounce(db, code="1A996001", kind="documents"):
    from app.models.email_message import EmailMessage
    db.add(EmailMessage(csp_id=code, to_email="loop@example.com", kind=kind,
                        subject="s", track_token=f"t-{code}", send_status="sent",
                        sent_at=NOW - timedelta(hours=3),
                        bounced_at=NOW - timedelta(hours=2),
                        bounce_reason="address not found"))
    db.commit()


@pytest.fixture
def senders(monkeypatch):
    """Stand-ins for everything that would reach a CSP."""
    from app.services import (documents_whatsapp, email_service,
                              message_sender)
    calls = {"ask": [], "email": [], "whatsapp": [], "ask_result": None,
             "paused": False}

    def ask(session, record, **kw):
        calls["ask"].append((record.csp_id, kw["channel"].kind,
                             kw.get("allow_email"), kw.get("verify")))
        return calls["ask_result"] or {"sent": True, "via": kw["channel"].kind}
    monkeypatch.setattr(message_sender, "ask_for_details", ask)
    monkeypatch.setattr(message_sender, "choose_channel",
                        lambda session, kind=None: SimpleNamespace(kind=kind))
    monkeypatch.setattr(email_service, "paused", lambda: calls["paused"])
    monkeypatch.setattr(email_service, "send_documents_email",
                        lambda **kw: calls["email"].append(kw) or True)
    monkeypatch.setattr(documents_whatsapp, "notify", lambda s, csp, job, names: (
        calls["whatsapp"].append((csp.mobile, names)) or {"status": "sent"}))
    monkeypatch.setattr(fl, "_documents", lambda session, csp_id: [
        ("CSP ID Card", SimpleNamespace(filename="id.pdf", file_data=b"%PDF-1.4"))])
    return calls


def _fix(db, code="1A996001"):
    db.expire_all()
    return db.execute(select(ContactFix).where(ContactFix.csp_id == code)
                      ).scalar_one()


def test_a_bad_whatsapp_number_is_asked_about_by_email_once(ldb, senders):
    _csp(ldb)
    _whatsapp(ldb)
    out = fl.run(ldb, SETTINGS)
    assert (out["found"], out["asked"]) == (1, 1)
    assert senders["ask"] == [("1A996001", "email", True, True)]
    fix = _fix(ldb)
    assert (fix.problem, fix.bad_value, fix.status, fix.asked_via) == (
        fl.WHATSAPP_UNDELIVERED, PHONE, "asked", "email")
    fl.run(ldb, SETTINGS)
    assert len(senders["ask"]) == 1, "asked once only"


def test_a_corrected_number_resends_the_documents_whatsapp(ldb, senders):
    from app.models.processing_job import ProcessingJob
    _csp(ldb)
    ldb.add(ProcessingJob(job_id="job-loop-1", csp_id="1A996001",
                          workflow_type="new_csp"))
    ldb.commit()
    _whatsapp(ldb, kind="documents_ready")
    fl.run(ldb, SETTINGS)
    ldb.execute(text("UPDATE csp_records SET mobile = '9812345602' "
                     "WHERE csp_id = '1A996001'"))
    ldb.commit()
    out = fl.run(ldb, SETTINGS)
    assert out["resent"] == 1
    assert senders["whatsapp"] == [("9812345602", ["CSP ID Card"])]
    fix = _fix(ldb)
    assert (fix.status, fix.corrected_value) == ("resent", "919812345602")


def test_a_corrected_number_for_a_details_request_needs_no_resend(ldb, senders):
    _csp(ldb)
    _whatsapp(ldb, kind="data_request")
    fl.run(ldb, SETTINGS)
    ldb.execute(text("UPDATE csp_records SET mobile = '9812345602'"))
    ldb.commit()
    fl.run(ldb, SETTINGS)
    assert _fix(ldb).status == "done"
    assert senders["whatsapp"] == []


def test_a_bounced_documents_email_is_asked_on_whatsapp_then_resent(ldb, senders):
    _csp(ldb)
    _bounce(ldb)
    fl.run(ldb, SETTINGS)
    assert senders["ask"] == [("1A996001", "whatsapp", True, True)]
    ldb.execute(text("UPDATE csp_records SET email = 'right@example.com'"))
    ldb.commit()
    out = fl.run(ldb, SETTINGS)
    assert out["resent"] == 1
    (sent,) = senders["email"]
    assert (sent["to_email"], sent["doc_names"]) == ("right@example.com",
                                                    ["CSP ID Card"])
    assert _fix(ldb).status == "resent"


def test_paused_emails_wait_without_using_a_try(ldb, senders):
    _csp(ldb)
    _bounce(ldb)
    fl.run(ldb, SETTINGS)
    ldb.execute(text("UPDATE csp_records SET email = 'right@example.com'"))
    ldb.commit()
    senders["paused"] = True
    for _ in range(4):
        fl.run(ldb, SETTINGS)
    fix = _fix(ldb)
    assert (fix.status, fix.tries) == ("corrected", 0)
    assert "paused" in fix.note and senders["email"] == []


def test_a_csp_on_hold_is_not_asked(ldb, senders):
    _csp(ldb, send_hold="Inactive in the Calling sheet")
    _whatsapp(ldb)
    fl.run(ldb, SETTINGS)
    assert senders["ask"] == []
    assert _fix(ldb).note.startswith("waiting: Inactive")


def test_three_failed_asks_stop_it(ldb, senders):
    _csp(ldb)
    _whatsapp(ldb)
    senders["ask_result"] = {"sent": False, "via": "email",
                             "reason": "SMTP refused"}
    for _ in range(4):
        fl.run(ldb, SETTINGS)
    fix = _fix(ldb)
    assert (fix.status, fix.tries) == ("stopped", 3)
    assert len(senders["ask"]) == 3


def test_a_number_that_later_worked_is_not_a_problem(ldb, senders):
    _csp(ldb)
    _whatsapp(ldb, when=NOW - timedelta(hours=3))
    _whatsapp(ldb, delivery="read", when=NOW - timedelta(hours=1))
    assert fl.run(ldb, SETTINGS)["found"] == 0


def test_no_email_to_ask_on_waits(ldb, senders):
    _csp(ldb, email=None)
    _whatsapp(ldb)
    fl.run(ldb, SETTINGS)
    fix = _fix(ldb)
    assert (fix.status, fix.tries, fix.note) == ("open", 0,
                                                 "no email address to ask on")


def test_the_job_never_runs_from_a_laptop_or_when_off(ldb, monkeypatch):
    from app.config import get_settings
    from app.workers import contact_loop_worker
    s = get_settings()
    monkeypatch.setattr(s, "public_app_url", "http://localhost:3000")
    assert "public address" in contact_loop_worker.run_once(ldb)["skipped"]
    monkeypatch.setattr(s, "contact_loop_enabled", False)
    assert "off" in contact_loop_worker.run_once(ldb)["skipped"]


def test_the_job_is_scheduled():
    from app.celery_app import celery_app
    tasks = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "workers.contact_loop" in tasks


@on_loop
async def test_contact_fixes_are_listed_for_admins(client, ldb, senders):
    _csp(ldb)
    _whatsapp(ldb)
    fl.run(ldb, SETTINGS)
    r = await client.get("/api/admin/quality/contact-fixes",
                         headers=_auth("rm"))
    assert r.status_code == 403
    r = await client.get("/api/admin/quality/contact-fixes",
                         headers=_auth("super_admin"))
    assert r.status_code == 200, r.text
    (row,) = r.json()["fixes"]
    assert (row["problem_label"], row["status"], row["asked_via"]) == (
        "WhatsApp did not reach the phone", "asked", "email")
