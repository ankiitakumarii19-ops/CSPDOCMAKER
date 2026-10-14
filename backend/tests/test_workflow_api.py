"""Existing-CSP workflow API against a real, migrated PostgreSQL database.

Covers the fixed defects: job creation (requested_by / workflow_type),
body-based process contract, confirm sending exactly the job's documents,
persistence of DocumentJob / ValidationResult / EmailJob, job ownership and
the admin monitor-only rule.
"""

import pytest
from sqlalchemy import select, func

from app.models import (
    CSPRecord, DocumentJob, EmailJob, ProcessingJob, User, ValidationResult,
)
from app.models.enums import (
    AccountStatus, EmailStatus, JobState, UserRole, ValidationType, WorkflowType,
)
from app.services import jwt_service

# The app's connection pool is shared across tests, so every test must run on
# the same (session-scoped) event loop as the fixtures.
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(autouse=True)
def _no_libreoffice_needed(stub_pdf_conversion):
    """Every workflow in this module converts PDFs through the stub."""



def _auth(user: User) -> dict:
    token = jwt_service.create_access_token(
        {"sub": user.email, "role": user.role.value, "name": user.name}
    )
    return {"Authorization": f"Bearer {token}"}


async def _user(db, email, role=UserRole.RM) -> User:
    u = User(email=email, name=email.split("@")[0], mobile="9876543210", role=role,
             account_status=AccountStatus.ACTIVE, password_hash="x")
    db.add(u)
    await db.commit()
    return u


@pytest.fixture(autouse=True)
def _output_dir(tmp_path, monkeypatch):
    from app.services import document_service
    monkeypatch.setattr(document_service.settings, "document_output_dir", str(tmp_path))


@pytest.fixture
async def csp(db):
    # Test fixture values only — not business data.
    record = CSPRecord(
        csp_id="TESTCSP001", csp_code="TC001", name="Test Csp Name",
        email="csp.test@example.com", address="1 Test Street",
        district="Testdistrict", state="Teststate",
    )
    db.add(record)
    await db.commit()
    return record


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar()


async def test_process_creates_persisted_job_and_awaits_confirmation(client, db, csp):
    rm = await _user(db, "rm1@eko.co.in")
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "awaiting_confirmation" and body["ready_to_send"]

    job = (await db.execute(select(ProcessingJob))).scalar_one()
    assert job.requested_by == rm.id
    assert job.workflow_type == WorkflowType.EXISTING_CSP
    assert job.current_state == JobState.AWAITING_CONFIRMATION

    docs = (await db.execute(select(DocumentJob))).scalars().all()
    assert [d.document_type.value for d in docs] == ["csp_certificate"]
    types = sorted(v.validation_type.value for v in
                   (await db.execute(select(ValidationResult))).scalars().all())
    assert types == sorted([ValidationType.DATA_VALIDATION.value,
                            ValidationType.DETERMINISTIC.value,
                            ValidationType.EMAIL_VALIDATION.value])


async def test_missing_data_keeps_the_request_pending(client, db):
    """Changed 11 Oct 2026 (tracker No. 53): the RM fills nothing. A
    request with missing details is kept as PENDING_DATA, with the
    documents chosen, and finished automatically later."""
    rm = await _user(db, "rm1@eko.co.in")
    db.add(CSPRecord(csp_id="TESTCSP002", name="No Code Csp", email="x@example.com",
                     district="Testdistrict", state="Teststate"))
    await db.commit()
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "TESTCSP002", "document_types": ["csp_certificate"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending_data"
    assert body["ready_to_send"] is False
    assert set(body["missing_fields"]) == {"CSP Code", "Address"}
    job = (await db.execute(select(ProcessingJob))).scalar_one()
    assert job.current_state == JobState.PENDING_DATA
    assert job.requested_documents == ["csp_certificate"]


async def test_a_pending_request_says_truthfully_whether_the_csp_was_asked(client, db):
    """12 Oct 2026: the CSP is asked straight away, and the RM is told what
    really happened — never "will be asked" when nothing went out."""
    rm = await _user(db, "rm1@eko.co.in")
    db.add(CSPRecord(csp_id="TESTCSP003", name="No Code Csp", email="x@example.com",
                     district="Testdistrict", state="Teststate"))
    await db.commit()
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "TESTCSP003", "document_types": ["csp_certificate"]},
    )
    body = r.json()
    assert body["status"] == "pending_data"
    asked = body["csp_asked"]
    assert asked["sent"] is False and asked["reason"], asked
    assert "has been asked" not in body["message"]
    assert asked["reason"] in body["message"]


async def test_a_pending_request_reports_a_successful_ask(client, db, monkeypatch):
    from app.services import message_sender
    calls = []

    def fake_ask(session, record, **kwargs):
        calls.append(record.csp_id)
        return {"csp_id": record.csp_id, "sent": True, "via": "whatsapp",
                "to": "91**", "reason": ""}
    monkeypatch.setattr(message_sender, "ask_for_details", fake_ask)
    rm = await _user(db, "rm1@eko.co.in")
    db.add(CSPRecord(csp_id="TESTCSP004", name="No Code Csp", email="x@example.com",
                     district="Testdistrict", state="Teststate"))
    await db.commit()
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "TESTCSP004", "document_types": ["csp_certificate"]},
    )
    body = r.json()
    assert calls == ["TESTCSP004"], "the CSP is asked once, right away"
    assert body["csp_asked"] == {"sent": True, "via": "whatsapp", "reason": ""}
    assert "has been asked for them on WhatsApp" in body["message"]
    job = (await db.execute(select(ProcessingJob))).scalar_one()
    assert job.current_state == JobState.PENDING_DATA, "still pending until the data is in"


async def test_confirm_sends_only_this_jobs_documents_and_persists_email(client, db, csp):
    rm = await _user(db, "rm1@eko.co.in")
    h = _auth(rm)
    # An older job generates a different document for the same CSP; the old
    # glob-based confirm would have attached it too. (csp_id_card cannot be
    # generated until image placement lands, so a second certificate is used.)
    await client.post("/api/workflows/process", headers=h,
                      json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]})
    r = await client.post("/api/workflows/process", headers=h,
                          json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]})
    job_id = r.json()["job_id"]

    r = await client.post(f"/api/workflows/{job_id}/confirm", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["documents_sent"] == 1
    assert r.json()["status"] == "email_sent"

    email = (await db.execute(select(EmailJob))).scalar_one()
    assert email.status == EmailStatus.SENT and email.sent_at is not None
    assert email.recipient == "csp.test@example.com"

    # A second confirm is rejected — no duplicate email.
    r = await client.post(f"/api/workflows/{job_id}/confirm", headers=h)
    assert r.status_code == 409
    assert await _count(db, EmailJob) == 1


async def test_rm_cannot_see_or_confirm_another_rms_job(client, db, csp):
    owner = await _user(db, "rm1@eko.co.in")
    other = await _user(db, "rm2@eko.co.in")
    r = await client.post("/api/workflows/process", headers=_auth(owner),
                          json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]})
    job_id = r.json()["job_id"]
    assert (await client.get(f"/api/workflows/{job_id}", headers=_auth(other))).status_code == 404
    assert (await client.post(f"/api/workflows/{job_id}/confirm",
                              headers=_auth(other))).status_code == 404
    assert await _count(db, EmailJob) == 0


async def test_admin_is_monitor_only(client, db, csp):
    admin = await _user(db, "admin1@eko.co.in", role=UserRole.ADMIN)
    r = await client.post("/api/workflows/process", headers=_auth(admin),
                          json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]})
    assert r.status_code == 403
    r = await client.post("/api/documents/generate/TESTCSP001", headers=_auth(admin),
                          json={"document_types": ["csp_certificate"]})
    assert r.status_code == 403
    assert await _count(db, ProcessingJob) == 0


async def test_admin_endpoints_return_real_counts(client, db, csp):
    admin = await _user(db, "admin1@eko.co.in", role=UserRole.ADMIN)
    rm = await _user(db, "rm1@eko.co.in")
    r = await client.post("/api/workflows/process", headers=_auth(rm),
                          json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]})
    await client.post(f"/api/workflows/{r.json()['job_id']}/confirm", headers=_auth(rm))

    r = await client.get("/api/admin/dashboard", headers=_auth(admin))
    assert r.status_code == 200, r.text
    m = r.json()["metrics"]
    assert m["total_csps"] == 1
    assert m["documents_generated_today"] == 1
    assert m["emails_sent_today"] == 1
    assert m["failed_emails_today"] == 0
    assert m["sms_failures_today"] == 0

    r = await client.get("/api/admin/jobs", headers=_auth(admin))
    assert r.status_code == 200, r.text
    assert r.json()["jobs"][0]["requested_by"] == "rm1@eko.co.in"

    r = await client.get("/api/admin/audit-logs", headers=_auth(admin))
    assert r.status_code == 200, r.text

    assert (await client.get("/api/admin/dashboard", headers=_auth(rm))).status_code == 403


# ---- PDF conversion, permanent storage, and what the CSP receives --------

async def test_process_stores_only_the_pdf_in_postgres(client, db, csp, tmp_path):
    """Rule since 12 Oct 2026 (No. 87): only the PDF is kept, in the
    database; the working DOCX is discarded."""
    from app.models.stored_document import StoredDocument
    from app.models.enums import DocumentFormat, DocumentType

    # The BCP needs more of the record filled in than the shared fixture has.
    from datetime import date
    csp.ao = "Test Ao"
    csp.asm_name = "Test Asm"
    csp.asm_email = "asm@example.com"
    csp.asm_contact = "9876543210"
    csp.branch_name = "Test Branch"
    csp.branch_code = "0001"
    csp.rbo_name = "Test Rbo"
    csp.mobile = "9876543210"
    csp.certificate_date = date(2026, 3, 4)
    await db.commit()

    rm = await _user(db, "rm1@eko.co.in")
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "TESTCSP001",
              "document_types": ["csp_certificate", "bcp"]},
    )
    assert r.status_code == 200, r.text

    rows = (await db.execute(select(StoredDocument))).scalars().all()
    stored = {(row.document_type, row.file_format) for row in rows}
    assert stored == {
        (DocumentType.CSP_CERTIFICATE, DocumentFormat.PDF),
        (DocumentType.BCP, DocumentFormat.PDF),
    }, "only the PDF is kept (No. 87)"
    leftover = [p.name for p in tmp_path.rglob("*.docx")]
    assert leftover == [], f"working DOCX files left on disk: {leftover}"
    # The bytes are really there, not just a row.
    for row in rows:
        assert row.file_size > 0
        assert len(row.file_data) == row.file_size
        assert row.csp_id == "TESTCSP001"


async def test_the_csp_receives_pdfs_not_docx(client, db, csp, monkeypatch):
    """The user's rule: convert to PDF, and send the PDF to the CSP."""
    from app.services import email_service

    captured = {}

    def fake_send(to_email, csp_name, csp_id, doc_names, doc_filepaths):
        captured["to"] = to_email
        captured["files"] = list(doc_filepaths)
        captured["bytes"] = [open(p, "rb").read(5) for p in doc_filepaths]
        return True

    monkeypatch.setattr(email_service, "send_documents_email", fake_send)

    rm = await _user(db, "rm1@eko.co.in")
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]},
    )
    job_id = r.json()["job_id"]
    confirm = await client.post(f"/api/workflows/{job_id}/confirm", headers=_auth(rm))
    assert confirm.status_code == 200, confirm.text

    assert captured["to"] == "csp.test@example.com"
    assert captured["files"], "no attachments were sent"
    assert all(p.lower().endswith(".pdf") for p in captured["files"]), captured["files"]
    assert all(b == b"%PDF-" for b in captured["bytes"]), "attachment was not a PDF"


async def test_a_conversion_failure_stops_the_workflow_and_sends_nothing(
    client, db, csp, monkeypatch
):
    """A CSP must never be sent a partial or unconverted set of documents."""
    from app.models.stored_document import StoredDocument
    from app.services import pdf_service

    def boom(paths, output_dir=None):
        raise pdf_service.PDFConversionError("LibreOffice fell over")

    monkeypatch.setattr(pdf_service, "convert_all", boom)

    rm = await _user(db, "rm1@eko.co.in")
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]},
    )
    assert r.status_code == 500

    job = (await db.execute(select(ProcessingJob))).scalar_one()
    assert job.current_state == JobState.FAILED_PDF_CONVERSION
    assert (await db.execute(select(StoredDocument))).scalars().all() == []
    assert await _count(db, EmailJob) == 0


async def test_confirm_refuses_when_the_stored_pdf_is_gone(client, db, csp):
    """Storage is the record; if it is missing, nothing gets sent."""
    from sqlalchemy import delete
    from app.models.stored_document import StoredDocument
    from app.models.enums import DocumentFormat

    rm = await _user(db, "rm1@eko.co.in")
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]},
    )
    job_id = r.json()["job_id"]

    await db.execute(delete(StoredDocument).where(
        StoredDocument.file_format == DocumentFormat.PDF))
    await db.commit()

    confirm = await client.post(f"/api/workflows/{job_id}/confirm", headers=_auth(rm))
    assert confirm.status_code == 409
    assert "Stored PDFs are missing" in confirm.json()["detail"]


async def test_a_sub_kos_bcp_alone_is_refused_plainly(client, db):
    """Tracker No. 57: the BCP is made for a KO only."""
    rm = await _user(db, "rm1@eko.co.in")
    db.add(CSPRecord(csp_id="1A8503447", csp_code="1A8503447",
                     name="Sub Ko", email="subko@example.com"))
    await db.commit()
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "1A8503447", "document_types": ["bcp"]},
    )
    assert r.status_code == 400
    assert "KO only" in r.json()["detail"]


async def _complete_csp(db, csp_id):
    """A CSP with every detail an ID Card and a CSP Certificate need, except
    the photo."""
    from app.models.enums import DocumentType
    from app.services import csp_mapping
    record = CSPRecord(csp_id=csp_id, csp_code=csp_id, name="Sheet Photo Csp",
                       email="sheet.photo@example.com")
    fields = set(csp_mapping.required_fields_for(DocumentType.CSP_ID_CARD)) | set(
        csp_mapping.required_fields_for(DocumentType.CSP_CERTIFICATE))
    for field in sorted(fields):
        attr = csp_mapping.FIELD_TO_CSP_ATTR.get(field)
        if attr and field != "photo" and not getattr(record, attr, None):
            setattr(record, attr, "9876543210" if "mobile" in field else "Test")
    db.add(record)
    await db.commit()
    return record


async def test_an_id_card_uses_the_photo_in_the_sheet(client, db, monkeypatch, tmp_path):
    """Tracker No. 99: the photo was in the sheet's Photo cell but the app
    never read it, so the ID Card failed with 'no usable photo'."""
    import io
    from PIL import Image
    from app.config import get_settings
    from app.services import csp_photo_service, sheet_photo_reader

    monkeypatch.setattr(get_settings(), "photo_placeholder_allowed", False)
    monkeypatch.setattr(csp_photo_service, "photo_directory", lambda: str(tmp_path))
    buf = io.BytesIO()
    Image.new("RGB", (350, 450), "white").save(buf, "JPEG")
    found = sheet_photo_reader.SheetPhotos(
        pictures={"1A000099": sheet_photo_reader.SheetPicture(
            data=buf.getvalue(), extension=".jpg", tab="KOData", row=2)},
        ambiguous={}, codes={"1A000099"})
    monkeypatch.setattr(sheet_photo_reader, "sheet_photos", lambda refresh=False: found)
    await _complete_csp(db, "1A000099")

    rm = await _user(db, "rm1@eko.co.in")
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "1A000099",
              "document_types": ["csp_id_card", "csp_certificate"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "awaiting_confirmation", r.json()
    saved = (await db.execute(select(CSPRecord.photo_url).where(
        CSPRecord.csp_id == "1A000099"))).scalar_one()
    assert saved and open(saved, "rb").read() == buf.getvalue()


async def test_no_photo_anywhere_waits_for_one_instead_of_failing(client, db, monkeypatch):
    """Tracker No. 99: a missing photo is missing data — the request is
    kept and the CSP asked — not a 'Document generation failed'."""
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "photo_placeholder_allowed", False)
    await _complete_csp(db, "1A000098")
    rm = await _user(db, "rm1@eko.co.in")
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "1A000098",
              "document_types": ["csp_id_card", "csp_certificate"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_data"
    assert r.json()["missing_fields"] == ["Photo"]


async def test_a_generation_failure_tells_the_rm_why(client, db, csp, monkeypatch):
    """Tracker No. 99: the screen said only 'Document generation failed.'"""
    from app.services import document_service

    def boom(*args, **kwargs):
        raise RuntimeError("Document generation failed for CSP_CERTIFICATE "
                           "(CSP TESTCSP001): the template is damaged")
    monkeypatch.setattr(document_service, "generate_documents", boom)

    rm = await _user(db, "rm1@eko.co.in")
    r = await client.post(
        "/api/workflows/process", headers=_auth(rm),
        json={"csp_id": "TESTCSP001", "document_types": ["csp_certificate"]},
    )
    assert r.status_code == 500
    assert "the template is damaged" in r.json()["detail"]["message"]
    job = (await db.execute(select(ProcessingJob))).scalar_one()
    assert job.current_state == JobState.FAILED_DOCUMENT_GENERATION
    assert "the template is damaged" in job.error_message
