"""EMAILS_PAUSED (No. 133, 22 Oct 2026): while the sending address is being
changed, no email goes out except the sign-in codes — and documents that are
due wait rather than being marked done."""

import pytest

from app.config import get_settings
from app.services import email_service, message_sender
from tests.test_new_csp_automation import (  # noqa: F401 — fixtures
    db, make_csp, no_crm, run, sent)


@pytest.fixture
def paused(monkeypatch):
    monkeypatch.setattr(get_settings(), "emails_paused", True)


@pytest.fixture
def smtp(monkeypatch):
    calls = []
    monkeypatch.setattr(get_settings(), "email_method", "smtp")
    monkeypatch.setattr(email_service, "_send_via_smtp",
                        lambda to, *a, **k: (calls.append(to), True)[1])
    return calls


def test_sign_in_codes_still_go_out(paused, smtp):
    assert email_service.send_otp_email("someone@eko.co.in", "123456")
    assert smtp == ["someone@eko.co.in"]


def test_documents_are_not_mailed(paused, smtp):
    assert email_service.send_documents_email(
        to_email="csp@example.com", csp_name="Csp", csp_id="1A1",
        doc_names=["ID Card"], doc_filepaths=[]) is False
    assert smtp == []


def test_other_emails_are_not_sent(paused, smtp):
    ok, why = message_sender._send_email("rm@eko.co.in", "Subject", "Body")
    assert ok is False and "paused" in why.lower()
    assert smtp == []


def test_a_ready_new_csp_waits_and_is_not_marked_done(
        db, no_crm, sent, monkeypatch, paused):
    make_csp(db, complete=True, photo="/nowhere.png")
    from app.services import studio_photo
    monkeypatch.setattr(studio_photo, "prepare_for", lambda csp: None)
    monkeypatch.setattr(
        "app.services.missing_data_service.check_missing_data",
        lambda csp, types: type("M", (), {"has_missing_data": False})())
    result = run()
    assert result["documents_sent"] == 0 and sent == []
    db.expire_all()
    from app.models.csp_record import CSPRecord
    record = db.query(CSPRecord).filter_by(csp_id="NEW1").one()
    assert record.new_csp_processed_at is None, \
        "picked up again once emails are turned back on"


def test_an_rm_cannot_send_documents_while_paused(paused):
    from fastapi import HTTPException

    from app.routers import workflow_router
    with pytest.raises(HTTPException) as e:
        workflow_router._refuse_while_emails_paused()
    assert e.value.status_code == 409
