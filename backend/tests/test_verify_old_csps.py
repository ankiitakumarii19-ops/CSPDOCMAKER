"""Old CSPs asked to verify their details (tracker No. 126).

WhatsApp (and Zoho) are stand-ins. Checked: who is asked and who is not,
the pace and hours, that a complete record is still asked to verify, that a
run of failures stops the batch, and that nothing is mailed.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.csp_record import CSPRecord
from app.services import field_ownership as fo
from app.workers import verify_old_csps_worker as w

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOON_IST = datetime(2026, 10, 22, 6, 30, tzinfo=timezone.utc)   # 12:00 IST
NIGHT_IST = datetime(2026, 10, 22, 17, 30, tzinfo=timezone.utc)  # 23:00 IST


@pytest.fixture
def db(migrated_db, monkeypatch):
    from app.services import email_service, message_sender, whatsapp_platform
    engine = create_engine(get_settings().database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg2://"))
    state = SimpleNamespace(sent=[], status=whatsapp_platform.SENT, mails=[])
    monkeypatch.setattr(message_sender, "choose_channel", lambda s: SimpleNamespace(
        kind="whatsapp", last_used_at=None, last_error=None))
    monkeypatch.setattr(message_sender, "choose_template", lambda s: SimpleNamespace(
        body="Namaste {name}, please confirm: {link}", subject=None,
        purpose="data_request"))
    monkeypatch.setattr(message_sender, "link_is_reachable", lambda link: True)
    monkeypatch.setattr(whatsapp_platform, "send", lambda to, body, values, **k: (
        state.sent.append((to, values)),
        {"status": state.status, "reason": "" if state.status == "sent"
         else "Meta has not approved the wording", "job_id": "j",
         "template_name": "t"})[1])
    monkeypatch.setattr(email_service, "send_documents_email",
                        lambda **kw: state.mails.append(kw) or True)
    monkeypatch.setattr(get_settings(), "verify_wait_for_address", False)
    with Session(engine) as s:
        s.execute(text("TRUNCATE data_requests, whatsapp_messages, "
                       "email_jobs, processing_jobs, csp_records, "
                       "source_sheet_states RESTART IDENTITY CASCADE"))
        s.execute(text("DELETE FROM sync_runs WHERE source = 'address'"))
        s.commit()
        state.session = s
        yield state
        s.rollback()
        s.execute(text("TRUNCATE data_requests, whatsapp_messages, "
                       "email_jobs, processing_jobs, csp_records, "
                       "source_sheet_states RESTART IDENTITY CASCADE"))
        s.commit()
    engine.dispose()


def _old(s, code, copied_in=True, **kw):
    """An old CSP; by default one copied in from the Calling sheet."""
    from app.models.source_sheet import SourceSheetState
    full = dict(name=f"Csp {code}", mobile="9000000" + code[-3:],
                email="x@example.com", address="Ward 1, Patna, 800001",
                gender="Female", district="Patna", state="Bihar",
                branch_name="B", branch_code="1", origin="baseline")
    full.update(kw)
    s.add(CSPRecord(csp_id=code, csp_code=code, **full))
    if copied_in:
        s.add(SourceSheetState(csp_code=code, in_calling=True,
                               imported_as="baseline"))


async def test_who_is_asked_and_who_is_not(db):
    from app.models.data_request import ANSWERED, DataRequest
    from app.models.email_job import EmailJob
    from app.models.enums import EmailStatus
    from app.models.processing_job import ProcessingJob
    s = db.session
    _old(s, "1A960001")                                   # asked
    _old(s, "1A960002", send_hold="Inactive in the Calling sheet")
    _old(s, "1A960003", mobile=None)
    _old(s, "1A960004", origin="new")                     # not an old CSP
    _old(s, "1A960005")                                   # already verified
    _old(s, "1A960006")                                   # already emailed
    _old(s, "1A960007", copied_in=False)    # was in CSPDATA before: never
    s.flush()
    s.add(DataRequest(csp_id="1A960005", token_hash="h5", fields=["name"],
                      status=ANSWERED,
                      expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    from app.models.enums import WorkflowType
    job = ProcessingJob(job_id="JOB-1", csp_id="1A960006",
                        workflow_type=WorkflowType.EXISTING_CSP)
    s.add(job)
    s.flush()
    s.add(EmailJob(processing_job_id=job.id, recipient="x@example.com",
                   subject="s", status=EmailStatus.SENT))
    s.commit()
    assert [c.csp_id for c in w.to_verify(s, 25)] == ["1A960001"]


async def test_a_complete_record_is_still_asked_and_nothing_is_mailed(
        db, monkeypatch):
    from app.services import data_request_service as drs
    monkeypatch.setattr(drs, "fields_to_ask", lambda r: [])   # nothing blank
    _old(db.session, "1A960011")
    db.session.commit()
    out = w.run_batch(db.session, now=NOON_IST)
    assert out["sent"] == ["1A960011"]
    [(to, values)] = db.sent
    assert values["fields"] == "all your details"
    assert db.mails == [], "verifying mails nothing"
    assert w.run_batch(db.session, now=NOON_IST)["sent"] == [], \
        "asked once — not again"


async def test_the_verification_link_asks_ao_and_rbo_even_when_known(db):
    from app.models.data_request import DataRequest
    _old(db.session, "1A960012", ao="Dumka AO", rbo_name="RBO 3")
    db.session.commit()
    assert w.run_batch(db.session, now=NOON_IST)["sent"] == ["1A960012"]
    request = db.session.execute(select(DataRequest).where(
        DataRequest.csp_id == "1A960012")).scalars().one()
    assert {"ao", "rbo_name"} <= set(request.fields)
    assert not {"dc", "asm_name", "rm_name", "lho"} & set(request.fields)


async def test_pace_and_hours(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "verify_batch_size", 3)
    for i in range(5):
        _old(db.session, f"1A96002{i}")
    db.session.commit()
    assert w.run_batch(db.session, now=NIGHT_IST) == {
        "skipped": "outside sending hours"}
    assert len(w.run_batch(db.session, now=NOON_IST)["sent"]) == 3
    assert len(w.run_batch(db.session, now=NOON_IST)["sent"]) == 2


async def test_a_run_of_failures_stops_the_batch(db, monkeypatch):
    from app.services import whatsapp_platform
    monkeypatch.setattr(get_settings(), "verify_stop_after", 2)
    db.status = whatsapp_platform.PENDING
    for i in range(5):
        _old(db.session, f"1A96003{i}")
    db.session.commit()
    out = w.run_batch(db.session, now=NOON_IST)
    assert out["sent"] == [] and len(out["not_sent"]) == 2, "stopped after 2"


async def test_the_form_no_longer_asks_which_documents_they_hold():
    assert not set(fo.form_fields()) & set(fo.DOCUMENTS_HELD)


async def test_verification_waits_until_the_address_tab_was_read(db, monkeypatch):
    from app.models.sync_run import SyncRun
    monkeypatch.setattr(get_settings(), "verify_wait_for_address", True)
    _old(db.session, "1A960041")
    db.session.commit()
    assert w.run_batch(db.session, now=NOON_IST) == {
        "skipped": "waiting for the Address tab to be read"}
    db.session.add(SyncRun(source="address", status="completed",
                           is_baseline=False))
    db.session.commit()
    assert w.run_batch(db.session, now=NOON_IST)["sent"] == ["1A960041"]
    db.session.execute(text("DELETE FROM sync_runs WHERE source = 'address'"))
    db.session.commit()


# ---- No. 136: failed sends are retried; one batch at a time ------------------

async def test_a_csp_whose_send_failed_is_tried_again_next_batch(db):
    from app.services import whatsapp_platform
    _old(db.session, "1A960051")
    db.session.commit()
    db.status = whatsapp_platform.FAILED
    assert w.run_batch(db.session, now=NOON_IST)["sent"] == []
    db.status = whatsapp_platform.SENT
    assert w.run_batch(db.session, now=NOON_IST)["sent"] == ["1A960051"], \
        "a failed ask does not block the CSP for 3 days"
    assert w.run_batch(db.session, now=NOON_IST)["sent"] == [], \
        "a delivered ask does"


async def test_only_one_batch_runs_at_a_time(db):
    _old(db.session, "1A960052")
    db.session.commit()
    holder = db.session.get_bind().connect()
    try:
        assert holder.execute(text("SELECT pg_try_advisory_lock(:k)"),
                              {"k": w.LOCK_KEY}).scalar()
        assert w.run_batch(db.session, now=NOON_IST) == {
            "skipped": "another verification batch is still running"}
        assert db.sent == []
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": w.LOCK_KEY})
        holder.close()
    assert w.run_batch(db.session, now=NOON_IST)["sent"] == ["1A960052"]


def test_the_supplied_verification_wording_is_the_new_one():
    import inspect

    from app.services import document_template_service as dts
    src = inspect.getsource(dts.sync_builtin_messages)
    assert "please confirm your details for your CSP" in src
    assert "your CSP documents need your details" not in src

