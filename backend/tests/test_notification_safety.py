"""OTP delivery safety: no plaintext OTP in logs or subjects, and no fake
success outside development.

SMS delivery was removed — an OTP is always emailed — so the mobile-number
normalisation and stub-SMS tests went with it."""

import logging

import pytest

from app.services import email_service


def test_otp_email_never_logs_otp_and_not_in_subject(monkeypatch, caplog):
    sent = {}

    def fake_smtp(to_email, subject, html_body, plain_body):
        sent["subject"] = subject
        return True

    monkeypatch.setattr(email_service.settings, "email_method", "smtp")
    monkeypatch.setattr(email_service, "_send_via_smtp", fake_smtp)
    with caplog.at_level(logging.DEBUG):
        assert email_service.send_otp_email("a@eko.co.in", "482913", "A")
    assert "482913" not in sent["subject"]
    assert "482913" not in caplog.text


@pytest.mark.parametrize("env", ["production", "staging"])
def test_console_email_refuses_outside_development(monkeypatch, env):
    monkeypatch.setattr(email_service.settings, "email_method", "console")
    monkeypatch.setattr(email_service.settings, "app_env", env)
    assert email_service.send_otp_email("a@eko.co.in", "482913") is False
    assert email_service.send_documents_email("c@x.com", "C", "CSP1", [], []) is False
