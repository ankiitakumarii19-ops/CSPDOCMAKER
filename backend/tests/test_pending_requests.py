"""RM requests that wait for data (tracker No. 53, 11 Oct 2026).

The RM only chooses a CSP and the documents. When details are missing the
request is kept as PENDING_DATA; once the sheet has the data, it is
finished automatically — made, checked, stored and emailed — exactly once.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.models.email_job import EmailJob
from app.models.enums import JobState, WorkflowType
from app.models.processing_job import ProcessingJob
from app.models.stored_document import StoredDocument
from app.workers import pending_request_worker
from tests.test_new_csp_automation import (  # noqa: F401  (fixtures)
    _fake_convert, _write_face, db, make_csp, photo_is_required, sent,
)


@pytest.fixture(autouse=True)
def _clean_jobs(db):
    db.execute(text("TRUNCATE processing_jobs RESTART IDENTITY CASCADE"))
    db.commit()


@pytest.fixture
def ready_pipeline(monkeypatch, tmp_path):
    """A real face photo, PDF conversion stubbed, files in a temp folder."""
    from app.services import csp_photo_service, document_service
    monkeypatch.setattr(document_service.settings, "document_output_dir",
                        str(tmp_path))
    photo = str(tmp_path / "face.png")
    _write_face(photo)
    monkeypatch.setattr(
        csp_photo_service, "fetch_photo",
        lambda csp: csp_photo_service.PhotoResult(False, reason="no_record"))
    monkeypatch.setattr("app.services.pdf_service.convert_all", _fake_convert)
    return photo


def _pending(db, csp_id, documents=("csp_certificate",), created=None):
    job = ProcessingJob(
        job_id=f"JOB-T-{csp_id}", csp_id=csp_id,
        workflow_type=WorkflowType.EXISTING_CSP,
        current_state=JobState.PENDING_DATA,
        requested_documents=list(documents),
    )
    if created:
        job.created_at = created
    db.add(job)
    db.commit()
    return job


def test_a_request_still_missing_details_keeps_waiting(db, sent, ready_pipeline):
    make_csp(db, "OLD1", complete=False, origin="baseline",
             photo=ready_pipeline)
    job = _pending(db, "OLD1")

    result = pending_request_worker.finish_ready(db)

    assert result["waiting"] == 1 and result["finished"] == 0
    db.refresh(job)
    assert job.current_state == JobState.PENDING_DATA
    assert sent == [], "nothing may be sent while anything is missing"
    assert db.execute(select(StoredDocument)).scalars().all() == []


def test_once_the_data_arrives_the_documents_are_made_and_sent(
        db, sent, ready_pipeline):
    csp = make_csp(db, "OLD2", complete=False, origin="baseline",
                   photo=ready_pipeline)
    job = _pending(db, "OLD2", documents=["csp_certificate"])
    assert pending_request_worker.finish_ready(db)["waiting"] == 1

    # The sheet sync brings the missing details in.
    csp.address, csp.mobile = "1 New Street", "9876543210"
    csp.branch_name, csp.branch_code = "Branch", "0001"
    csp.rbo_name, csp.ao = "Rbo", "Testao"
    csp.asm_name, csp.asm_email = "Test Asm", "asm@example.com"
    csp.asm_contact, csp.certificate_date = "9876543211", datetime.now().date()
    db.commit()

    result = pending_request_worker.finish_ready(db)
    assert result["finished"] == 1, result

    db.refresh(job)
    assert job.current_state == JobState.EMAIL_SENT
    rows = db.execute(select(StoredDocument)).scalars().all()
    assert {r.document_type.value for r in rows} == {"csp_certificate"}, (
        "exactly the documents the RM chose")
    assert len(sent) == 1 and sent[0]["to_email"] == csp.email
    email = db.execute(select(EmailJob)).scalar_one()
    assert email.processing_job_id == job.id

    # Run again: nothing is sent a second time.
    assert pending_request_worker.finish_ready(db)["pending"] == 0
    assert len(sent) == 1


def test_a_new_csp_waits_for_the_automatic_run_instead_of_doubling_it(
        db, sent, ready_pipeline):
    csp = make_csp(db, "NEW9", complete=True, origin="new",
                   photo=ready_pipeline, processed=None)
    job = _pending(db, "NEW9")

    assert pending_request_worker.finish_ready(db)["waiting"] == 1
    assert sent == []

    # The automatic new-CSP run sends everything...
    csp.new_csp_processed_at = datetime.now(timezone.utc)
    db.commit()
    pending_request_worker.finish_ready(db)

    # ...and the RM's request is closed by it, not sent again.
    db.refresh(job)
    assert job.current_state == JobState.COMPLETED
    assert sent == []


def test_a_new_csp_processed_long_before_the_request_is_finished_normally(
        db, sent, ready_pipeline):
    earlier = datetime.now(timezone.utc) - timedelta(days=30)
    make_csp(db, "NEW8", complete=True, origin="new", photo=ready_pipeline,
             processed=earlier)
    db.execute(text("UPDATE csp_records SET certificate_date = CURRENT_DATE "
                    "WHERE csp_id = 'NEW8'"))
    db.commit()
    job = _pending(db, "NEW8")

    assert pending_request_worker.finish_ready(db)["finished"] == 1
    db.refresh(job)
    assert job.current_state == JobState.EMAIL_SENT
    assert len(sent) == 1


def test_the_job_is_scheduled():
    from app.celery_app import celery_app
    names = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "workers.complete_pending_requests" in names
