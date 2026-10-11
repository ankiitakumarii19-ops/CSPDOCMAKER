"""KO and Sub-KO (tracker No. 57, 11 Oct 2026).

A KO's CSP code has 8 characters; a Sub-KO's is its KO's code plus one or
two more. The length decides the Training Certificate's wording, whether a
BCP is made, and which tab of the sheet the row is in.
"""

import pytest

from app.models.csp_record import CSPRecord
from app.models.enums import DocumentType
from app.services import (
    document_service, document_validation_service as dv, ko_level,
)
from app.services.missing_data_service import check_missing_data


@pytest.mark.parametrize("code,level", [
    ("1A850344", ko_level.KO),
    ("1A8503447", ko_level.SUB_KO),
    ("1A85034408", ko_level.SUB_KO),
    (" 1A850344 ", ko_level.KO),
    ("1A85034", None),
    ("1A850344081", None),
    ("", None),
    (None, None),
])
def test_the_length_of_the_code_decides(code, level):
    assert ko_level.level_of(code) == level


def test_a_sub_ko_names_its_ko():
    assert ko_level.parent_ko_code("1A85034408") == "1A850344"
    assert ko_level.parent_ko_code("1A850344") is None


def test_a_sub_ko_never_gets_a_bcp():
    everything = list(DocumentType)
    assert DocumentType.BCP in ko_level.allowed_documents("1A850344", everything)
    assert DocumentType.BCP not in ko_level.allowed_documents(
        "1A8503447", everything)
    assert ko_level.allowed_documents("1A8503447", [DocumentType.BCP]) == []


def test_each_tab_is_chosen_by_the_code():
    from app.config import get_settings
    s = get_settings()
    assert s.csp_tab_for("1A850344") == s.google_sheets_csp_sheet_name
    assert s.csp_tab_for("1A85034408") == s.google_sheets_subko_sheet_name


def _csp(code, **extra):
    values = dict(
        csp_id=code, csp_code=code, name="Level Test", gender="Female",
        branch_name="Branch", branch_code="0001", address="1 Street",
        district="D", state="S", mobile="9876543210",
        email="level@example.com", photo_url=None,
    )
    values.update(extra)
    return CSPRecord(**values)


@pytest.mark.parametrize("code,wording,not_wording", [
    ("1A850344", "bearing KO Code 1A850344", "Sub-KO Code"),
    ("1A8503447", "bearing Sub-KO Code 1A8503447", "KO/Sub-KO"),
    ("1A85034408", "bearing Sub-KO Code 1A85034408", "KO/Sub-KO"),
])
def test_the_training_certificate_says_ko_or_sub_ko(
        code, wording, not_wording, tmp_path, monkeypatch):
    from app.services import template_service
    monkeypatch.setattr(document_service.settings, "document_output_dir",
                        str(tmp_path))
    csp = _csp(code, photo_url=template_service.PLACEHOLDER_PHOTO)
    (_, path), = document_service.generate_documents(
        csp, [DocumentType.TRAINING_CERTIFICATE])
    text = " ".join(dv._extract_document_text(path).split())
    assert wording in text
    assert not_wording not in text
    ok, results = dv.validate_all_documents(
        csp, [(DocumentType.TRAINING_CERTIFICATE, path)])
    assert ok, results


def test_an_unknown_length_keeps_the_general_wording(tmp_path, monkeypatch):
    from app.services import template_service
    monkeypatch.setattr(document_service.settings, "document_output_dir",
                        str(tmp_path))
    csp = _csp("1A85034", photo_url=template_service.PLACEHOLDER_PHOTO)
    (_, path), = document_service.generate_documents(
        csp, [DocumentType.TRAINING_CERTIFICATE])
    assert "KO/Sub-KO" in dv._extract_document_text(path)


def test_asking_for_a_sub_kos_bcp_makes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(document_service.settings, "document_output_dir",
                        str(tmp_path))
    assert document_service.generate_documents(
        _csp("1A8503447", ao="AO", rbo_name="R"), [DocumentType.BCP]) == []


def test_a_sub_ko_is_never_missing_bcp_details():
    """The BCP needs AO, RBO and ASM; a Sub-KO without them is not blocked."""
    check = check_missing_data(_csp("1A8503447"), [DocumentType.BCP])
    assert check.has_missing_data is False
    assert check.documents == []
