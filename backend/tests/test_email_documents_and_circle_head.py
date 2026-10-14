"""Per-document delivery counts, and the Circle Head filter.

Two things the admin dashboard needs that the schema could not answer before:
which documents a given email carried, and which Circle Head covers a CSP.
"""

import uuid

import pytest

from app.models.csp_record import CSPRecord
from app.models.email_document import EmailDocument
from app.models.email_job import EmailJob
from app.models.enums import DocumentType, EmailStatus, JobState, WorkflowType
from app.models.processing_job import ProcessingJob
from app.models.user import User
from app.models.enums import AccountStatus, UserRole
from app.services import jwt_service
from app.services.info_directory import CIRCLE_HEAD, InfoDirectory

pytestmark = pytest.mark.asyncio(loop_scope="session")

ADMIN = "admin.metrics@eko.co.in"


@pytest.fixture
async def admin_headers(db):
    db.add(User(email=ADMIN, name="Admin", mobile="9876543210",
                role=UserRole.ADMIN, account_status=AccountStatus.ACTIVE,
                password_hash="x"))
    await db.commit()
    token = jwt_service.create_access_token(
        {"sub": ADMIN, "role": UserRole.ADMIN.value, "name": "Admin"})
    return {"Authorization": f"Bearer {token}"}


# ---- Circle Head from the INFO tab -------------------------------------

INFO_ROWS = [
    ["Circle Head Name", "Email ID", "Mobile Number", "LHO", "State"],
    ["Asha Rao", "asha@eko.co.in", "9000000001", "Patna", "Bihar"],
    ["Vikram Sen", "vikram@eko.co.in", "9000000002", "Chandigarh",
     "Haryana, Punjab"],
    [],
    ["ASM Name", "Email ID", "Mobile Number", "LHO", "State"],
    ["Neha Gupta", "neha@eko.co.in", "9000000003", "Patna", "Bihar"],
]


async def test_circle_head_is_filled_from_territory():
    info = InfoDirectory.from_rows(INFO_ROWS)
    filled = info.fill_missing({"lho": "Patna", "state": "Bihar"})
    assert filled["circle_head"] == "Asha Rao"


async def test_a_circle_head_already_on_the_row_is_not_overwritten():
    """The CSP sheet stays the source of truth wherever it has a value."""
    info = InfoDirectory.from_rows(INFO_ROWS)
    filled = info.fill_missing(
        {"lho": "Patna", "state": "Bihar", "circle_head": "Someone Else"})
    assert "circle_head" not in filled


async def test_an_ambiguous_territory_fills_nothing():
    """Two heads covering one LHO must leave the field missing, not guess."""
    rows = INFO_ROWS + [["Ravi Menon", "ravi@eko.co.in", "9000000004",
                         "Patna", "Bihar"]]
    info = InfoDirectory.from_rows(rows)
    # The extra row lands in the ASM block, so build a Circle Head clash.
    clash = [
        ["Circle Head Name", "Email ID", "Mobile Number", "LHO", "State"],
        ["Asha Rao", "asha@eko.co.in", "9", "Patna", "Bihar"],
        ["Ravi Menon", "ravi@eko.co.in", "9", "Patna", "Bihar"],
    ]
    assert "circle_head" not in InfoDirectory.from_rows(clash).fill_missing(
        {"lho": "Patna", "state": "Bihar"})
    assert len([p for p in info.people if p.role == CIRCLE_HEAD]) == 2


async def test_circle_head_filters_the_admin_metrics(client, db, admin_headers):
    for csp_id, head in (("CH0001", "Asha Rao"), ("CH0002", "Vikram Sen")):
        db.add(CSPRecord(csp_id=csp_id, source_row_identifier=csp_id,
                         name=f"CSP {csp_id}", origin="new",
                         circle_head=head))
    await db.commit()

    r = await client.get("/api/admin/csp-metrics?ch=Asha Rao",
                         headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filters_applied"] == {"ch": "Asha Rao"}
    assert body["totals"]["csps"] == 1

    options = (await client.get("/api/admin/csp-filters",
                                headers=admin_headers)).json()["filters"]
    assert "Asha Rao" in options["ch"]


# ---- which documents an email carried ----------------------------------

async def _job_with_email(db, csp_id: str, status: EmailStatus, doc_types):
    db.add(CSPRecord(csp_id=csp_id, source_row_identifier=csp_id,
                     name=f"CSP {csp_id}", origin="new"))
    job = ProcessingJob(
        job_id=f"JOB-{uuid.uuid4().hex[:8]}", csp_id=csp_id,
        workflow_type=WorkflowType.NEW_CSP, current_state=JobState.EMAIL_SENT,
    )
    db.add(job)
    await db.flush()
    email = EmailJob(processing_job_id=job.id, recipient="csp@example.com",
                     subject="Your CSP Documents", status=status)
    email.documents = [EmailDocument(document_type=d) for d in doc_types]
    db.add(email)
    await db.commit()
    return email


async def test_counts_are_per_document_not_per_email(client, db, admin_headers):
    """One email carrying three documents counts once for each of them."""
    three = [DocumentType.CSP_ID_CARD, DocumentType.CSP_CERTIFICATE,
             DocumentType.BCP]
    await _job_with_email(db, "ED0001", EmailStatus.SENT, three)
    await _job_with_email(db, "ED0002", EmailStatus.FAILED,
                          [DocumentType.CSP_ID_CARD])

    body = (await client.get("/api/admin/csp-metrics",
                             headers=admin_headers)).json()
    per_doc = {d["document_type"]: d for d in body["documents"]}

    assert per_doc[DocumentType.CSP_ID_CARD.value]["mailed"] == 1
    assert per_doc[DocumentType.CSP_ID_CARD.value]["failed"] == 1
    assert per_doc[DocumentType.BCP.value]["mailed"] == 1
    assert per_doc[DocumentType.BCP.value]["failed"] == 0
    # A document that no email carried stays at zero and counts as pending.
    training = per_doc[DocumentType.TRAINING_CERTIFICATE.value]
    assert training["mailed"] == 0 and training["failed"] == 0

    # The three buckets partition the population on every row.
    total = body["totals"]["csps"]
    for row in body["documents"]:
        assert row["mailed"] + row["pending"] + row["failed"] == total, row


async def test_a_retry_that_succeeded_counts_as_mailed_only(client, db,
                                                            admin_headers):
    """A CSP that failed and was later mailed must not appear in both."""
    await _job_with_email(db, "ED0005", EmailStatus.FAILED, [DocumentType.BCP])
    await _job_with_email(db, "ED0005b", EmailStatus.SENT, [DocumentType.BCP])
    # Point both jobs at the same CSP.
    from sqlalchemy import update

    from app.models.processing_job import ProcessingJob
    await db.execute(update(ProcessingJob)
                     .where(ProcessingJob.csp_id == "ED0005b")
                     .values(csp_id="ED0005"))
    await db.commit()

    body = (await client.get("/api/admin/csp-metrics?rm=",
                             headers=admin_headers)).json()
    row = {d["document_type"]: d for d in body["documents"]}[
        DocumentType.BCP.value]
    assert row["failed"] == 0, "the later success must win"
    assert row["mailed"] >= 1


async def test_a_document_cannot_be_recorded_twice_on_one_email(db):
    from sqlalchemy.exc import IntegrityError

    email = await _job_with_email(db, "ED0003", EmailStatus.SENT,
                                  [DocumentType.BCP])
    db.add(EmailDocument(email_job_id=email.id, document_type=DocumentType.BCP))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_deleting_the_email_deletes_its_document_rows(db):
    from sqlalchemy import func, select

    email = await _job_with_email(db, "ED0004", EmailStatus.SENT,
                                  [DocumentType.BCP, DocumentType.CSP_ID_CARD])
    email_id = email.id
    await db.delete(email)
    await db.commit()

    left = (await db.execute(
        select(func.count()).select_from(EmailDocument)
        .where(EmailDocument.email_job_id == email_id)
    )).scalar()
    assert left == 0


# ---- the admin search's CSP panel (No. 101) -----------------------------

async def test_the_csp_panel_says_where_each_document_stands(client, db, admin_headers):
    """The top-bar search opens one CSP: details, and per document whether
    it was made and mailed — decided as the dashboard decides it."""
    import hashlib
    from app.models.enums import DocumentFormat
    from app.models.stored_document import StoredDocument

    await _job_with_email(db, "1A900001", EmailStatus.SENT,
                          [DocumentType.CSP_ID_CARD])
    job = ProcessingJob(job_id=f"JOB-{uuid.uuid4().hex[:8]}", csp_id="1A900001",
                        workflow_type=WorkflowType.NEW_CSP,
                        current_state=JobState.EMAIL_SENT)
    db.add(job)
    await db.flush()
    failed = EmailJob(processing_job_id=job.id, recipient="csp@example.com",
                      subject="Your CSP Documents", status=EmailStatus.FAILED)
    failed.documents = [EmailDocument(document_type=DocumentType.CSP_CERTIFICATE)]
    db.add(failed)
    pdf = b"%PDF-1.4 test"
    db.add(StoredDocument(
        csp_id="1A900001", document_type=DocumentType.CSP_ID_CARD,
        file_format=DocumentFormat.PDF, version=2, filename="ID.pdf",
        content_type="application/pdf", file_data=pdf, file_size=len(pdf),
        checksum=hashlib.sha256(pdf).hexdigest()))
    await db.commit()

    r = await client.get("/api/admin/csp/1A900001/summary", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["csp"]["csp_id"] == "1A900001"
    docs = {d["document_type"]: d for d in body["documents"]}
    card = docs[DocumentType.CSP_ID_CARD.value]
    assert (card["generated"], card["version"], card["delivery"]) == (True, 2, "mailed")
    assert docs[DocumentType.CSP_CERTIFICATE.value]["delivery"] == "failed"
    assert docs[DocumentType.CSP_CERTIFICATE.value]["generated"] is False
    assert docs[DocumentType.TRAINING_CERTIFICATE.value]["delivery"] == "pending"


async def test_the_csp_panel_is_for_admins_and_reports_a_missing_csp(client, db, admin_headers):
    r = await client.get("/api/admin/csp/NO-SUCH/summary", headers=admin_headers)
    assert r.status_code == 404
    rm = jwt_service.create_access_token(
        {"sub": "rm.panel@eko.co.in", "role": "rm", "name": "Rm"})
    r = await client.get("/api/admin/csp/NO-SUCH/summary",
                         headers={"Authorization": f"Bearer {rm}"})
    assert r.status_code == 403
