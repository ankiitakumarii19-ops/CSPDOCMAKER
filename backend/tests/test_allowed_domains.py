"""Which email domains may sign in.

Staff use two company domains, so the check is a list rather than one
string. What matters is that widening it did not turn into "anything that
merely ends with the text" — @notekosupport.in must still be refused.
"""

import pytest

from app.config import Settings

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _settings(value: str) -> Settings:
    return Settings(ALLOWED_EMAIL_DOMAIN=value)


async def test_both_company_domains_are_allowed():
    s = _settings("eko.co.in,ekosupport.in")
    assert s.email_domain_allowed("someone@eko.co.in")
    assert s.email_domain_allowed("someone@ekosupport.in")


async def test_an_outside_domain_is_refused():
    s = _settings("eko.co.in,ekosupport.in")
    assert not s.email_domain_allowed("someone@gmail.com")


async def test_a_lookalike_domain_is_refused():
    """The check is on '@domain', not a bare suffix."""
    s = _settings("eko.co.in,ekosupport.in")
    assert not s.email_domain_allowed("someone@notekosupport.in")
    assert not s.email_domain_allowed("someone@eko.co.in.evil.com")


async def test_the_check_ignores_case_and_spacing():
    s = _settings(" eko.co.in , @ekosupport.in ")
    assert s.allowed_email_domains == ("eko.co.in", "ekosupport.in")
    assert s.email_domain_allowed("  SOMEONE@EkoSupport.IN  ")


async def test_one_domain_still_works():
    """An existing ALLOWED_EMAIL_DOMAIN=eko.co.in must keep working."""
    s = _settings("eko.co.in")
    assert s.email_domain_allowed("a@eko.co.in")
    assert not s.email_domain_allowed("a@ekosupport.in")
    assert s.allowed_email_domains_text == "@eko.co.in"


async def test_the_message_names_every_domain():
    s = _settings("eko.co.in,ekosupport.in")
    assert s.allowed_email_domains_text == "@eko.co.in or @ekosupport.in"


async def test_an_empty_address_is_refused():
    s = _settings("eko.co.in,ekosupport.in")
    assert not s.email_domain_allowed("")


# ---- the sign-in screen reads the rule from the server -----------------

async def test_the_sign_in_screen_accepts_any_address(client):
    """No server-wide domain rule since No. 120: anyone may create a
    workspace, and each workspace's Owner chooses who may join it."""
    r = await client.get("/api/auth/config")
    assert r.status_code == 200, r.text
    assert r.json() == {"allowed_email_domains": [],
                        "allowed_email_domains_text": "any"}


async def test_the_config_endpoint_needs_no_token(client):
    """The login screen reads it before anyone is signed in."""
    r = await client.get("/api/auth/config")
    assert r.status_code == 200


# ---- signup enforces it ------------------------------------------------

async def test_an_rm_nobody_added_cannot_sign_up(client, monkeypatch):
    """Any address may now try, but an RM still needs a workspace to have
    added them (or Eko's Authorization sheet to list them)."""
    from app.services import google_sheets_service
    monkeypatch.setattr(google_sheets_service, "check_authorization",
                        lambda email, role: (False, None))
    r = await client.post("/api/auth/signup", json={
        "email": "outsider@gmail.com", "name": "Outsider",
        "password": "CorrectHorse9!", "requested_role": "rm",
    })
    assert r.status_code != 200
    assert "has not been added" in r.text


async def test_signup_still_requires_authorization_on_an_allowed_domain(client):
    """Widening the domain must not let an unlisted person in."""
    r = await client.post("/api/auth/signup", json={
        "email": "stranger@ekosupport.in", "name": "Stranger",
        "password": "CorrectHorse9!", "requested_role": "rm",
    })
    assert r.status_code != 200, "the authorization sheet still governs"
