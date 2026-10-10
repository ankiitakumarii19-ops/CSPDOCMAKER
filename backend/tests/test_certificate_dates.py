"""The Training Certificate date and the BCP month/year are the date the
document is MADE — not CSP onboarding data.

Confirmed formats: Training Certificate `15.08.2024`, BCP `March 2026`.
For a new CSP the date is generated; for an existing CSP the RM supplies it
and it is stored on the CSP record for reuse.
"""

from datetime import date, datetime

import pytest

from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType, ValidationStatus
from app.services import csp_mapping, document_service, document_validation_service
from app.services.missing_data_service import check_missing_data, required_fields


def _csp(**overrides) -> CSPRecord:
    values = dict(
        csp_id="TESTCSP001", csp_code="TC001", name="Test Csp Name",
        branch_name="Testbranch", branch_code="BR0001", address="1 Test Street",
        district="Testdistrict", state="Teststate", mobile="9876543210",
        email="test.csp@example.com", ao="Testao", rbo_name="Testrbo",
        asm_name="Testasm", asm_email="test.asm@example.com", asm_contact="9876500000",
    )
    values.update(overrides)
    return CSPRecord(**values)


def test_formats():
    assert document_service.certificate_date(datetime(2024, 8, 15, 10, 30)) == "15.08.2024"
    assert document_service.certificate_month_year(date(2026, 3, 4)) == "March 2026"


def test_onboarding_fields_are_gone():
    labels = set(csp_mapping.FIELD_LABELS)
    assert not labels & {"onboarded_date", "onboarding_month", "onboarding_year"}
    assert not hasattr(CSPRecord, "onboarding_month")


@pytest.mark.parametrize("doc_type", [
    DocumentType.TRAINING_CERTIFICATE, DocumentType.BCP,
])
def test_certificate_date_is_required_for_dated_documents(doc_type):
    """The RM must supply it for an existing CSP, so it is a missing-data field."""
    assert "certificate_date" in {f[0] for f in required_fields(doc_type)}


@pytest.mark.parametrize("doc_type", [
    DocumentType.CSP_ID_CARD, DocumentType.CSP_CERTIFICATE,
])
def test_undated_documents_do_not_require_a_date(doc_type):
    assert "certificate_date" not in {f[0] for f in required_fields(doc_type)}


def test_the_date_is_never_missing_data():
    """Confirmed rule: a certificate carries the day it is made.

    There is therefore always a date to print, and a document is never
    held up waiting for somebody to supply one.
    """
    result = check_missing_data(_csp(), [DocumentType.BCP])
    missing = {f.field_name for d in result.documents for f in d.missing_fields}
    assert "certificate_date" not in missing
    assert result.has_missing_data is False


def test_complete_csp_with_a_stored_date_has_nothing_missing():
    result = check_missing_data(
        _csp(certificate_date=date(2026, 3, 4)), [DocumentType.BCP],
    )
    assert result.has_missing_data is False, result.model_dump()


def test_a_saved_date_is_ignored_and_today_is_printed(tmp_path):
    """Changed 11 Oct 2026 (tracker No. 56): the certificate date is always
    the day the document is made, even if an older date is on the record."""
    csp = _csp(certificate_date=date(2019, 3, 4))
    docs = document_service.generate_documents(csp, [DocumentType.BCP], None)
    text = document_validation_service._extract_document_text(docs[0][1])
    assert date.today().strftime("%B %Y") in text
    assert "March 2019" not in text

    all_passed, results = document_validation_service.validate_all_documents(csp, docs)
    assert all_passed, results
    assert results[0]["validation_status"] == ValidationStatus.PASSED.value


def test_validation_fails_when_the_printed_date_is_not_the_runs_date(tmp_path):
    """A document made with one date must not validate against another."""
    csp = _csp()
    docs = document_service.generate_documents(
        csp, [DocumentType.BCP], date(2026, 3, 4))
    status, issues = document_validation_service.validate_document(
        csp, DocumentType.BCP, docs[0][1], date(2024, 8, 15),
    )
    assert status == ValidationStatus.FAILED
    assert any(i["expected"] == "August 2024" for i in issues), issues


def test_training_certificate_prints_the_date(tmp_path, monkeypatch):
    """The Training Certificate carries the photo AND the made-on date."""
    monkeypatch.setattr(document_service.settings, "document_output_dir", str(tmp_path))
    csp = _csp(certificate_date=date(2024, 8, 15))   # ignored (No. 56)
    (_, path), = document_service.generate_documents(
        csp, [DocumentType.TRAINING_CERTIFICATE], None)
    text = document_validation_service._extract_document_text(path)
    assert date.today().strftime("%d.%m.%Y") in text
    assert "15.08.2024" not in text
    all_passed, results = document_validation_service.validate_all_documents(
        csp, [(DocumentType.TRAINING_CERTIFICATE, path)])
    assert all_passed, results


# ---- every CSP is dated the day the document is made (No. 56) ------------

def _record(origin, certificate_date=None):
    from app.models.csp_record import CSPRecord
    return CSPRecord(
        csp_id="X1", csp_code="X1", name="Date Test", email="d@example.com",
        address="1 Street", mobile="9876543210", branch_name="Br",
        branch_code="1", rbo_name="Rbo", origin=origin,
        certificate_date=certificate_date,
    )


def test_a_new_csp_is_dated_today_without_asking_anyone():
    """Confirmed rule: a new CSP is processed the day it appears."""
    from datetime import date
    assert csp_mapping.effective_certificate_date(_record("new")) == date.today()


def test_an_existing_csp_is_dated_the_day_it_is_made():
    """It used to return None and wait for the RM. It no longer does."""
    from datetime import date as _date

    assert csp_mapping.effective_certificate_date(
        _record("baseline")) == _date.today()


def test_a_new_csp_is_dated_the_same_way():
    from datetime import date as _date

    assert csp_mapping.effective_certificate_date(
        _record("new")) == _date.today()


def test_the_date_is_never_unknown():
    """Nothing can be blocked by it, because it is never absent."""
    for origin in ("new", "baseline", None, "anything"):
        assert csp_mapping.effective_certificate_date(
            _record(origin)) is not None


def test_a_saved_date_never_replaces_today():
    """Tracker No. 56: always the date the document is made."""
    from datetime import date
    stored = date(2019, 1, 19)
    for origin in ("new", "baseline"):
        assert csp_mapping.effective_certificate_date(
            _record(origin, stored)) == date.today()


def test_an_explicit_date_beats_everything():
    from datetime import date
    asked = date(2026, 3, 4)
    assert csp_mapping.effective_certificate_date(
        _record("new", date(2019, 1, 19)), asked) == asked


def test_a_new_csp_is_not_blocked_on_the_certificate_date():
    """This is what makes new-CSP automation possible at all."""
    from app.models.enums import DocumentType
    from app.services.missing_data_service import check_missing_data
    result = check_missing_data(_record("new"), list(DocumentType))
    missing = {f.field_name for d in result.documents for f in d.missing_fields}
    assert "certificate_date" not in missing


def test_an_existing_csp_is_not_asked_for_a_date():
    """Their RM is not made to remember when somebody was onboarded."""
    from app.models.enums import DocumentType
    from app.services.missing_data_service import check_missing_data
    result = check_missing_data(_record("baseline"), list(DocumentType))
    missing = {f.field_name for d in result.documents for f in d.missing_fields}
    assert "certificate_date" not in missing
