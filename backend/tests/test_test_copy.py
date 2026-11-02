# -*- coding: utf-8 -*-
"""A test copy of the app never messages anyone (No. 173)."""

import pytest

from app.config import get_settings
from app.services import email_service, whatsapp_platform


@pytest.fixture
def test_copy(monkeypatch):
    monkeypatch.setattr(get_settings(), "test_copy", True)
    monkeypatch.setattr(get_settings(), "emails_paused", False)


def test_no_whatsapp_goes_from_a_test_copy(test_copy, monkeypatch):
    monkeypatch.setattr(whatsapp_platform, "call_tool",
                        lambda *a, **k: pytest.fail("the platform was called"))
    result = whatsapp_platform.send("9812345670", "Hello {{name}}",
                                    {"name": "Csp"}, source_name="test")
    assert result["status"] == whatsapp_platform.FAILED
    assert "TEST_COPY" in result["reason"]


def test_emails_are_held_on_a_test_copy(test_copy):
    assert email_service.paused() is True


def test_the_live_app_is_unchanged(monkeypatch):
    monkeypatch.setattr(get_settings(), "test_copy", False)
    monkeypatch.setattr(get_settings(), "emails_paused", False)
    assert email_service.paused() is False


@pytest.mark.asyncio(loop_scope="session")
async def test_the_screens_are_told(client, test_copy):
    assert (await client.get("/api/auth/config")).json()["test_copy"] is True
