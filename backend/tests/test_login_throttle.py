# -*- coding: utf-8 -*-
"""Password guessing is slowed down.

The login had no limit at all. A password plus an OTP is a good design,
but an unlimited password check turns a weak password into a matter of
time rather than luck.

Two counters, because they stop different attacks: one account guessed at
from anywhere, and one source spraying a common password across many
accounts. And a lockout that always expires — a permanent one would let
anyone deny a real RM their job just by failing to log in as them.
"""

import pytest

from app.services import login_throttle as throttle

pytestmark = pytest.mark.asyncio(loop_scope="session")

EMAIL = "someone@eko.co.in"
IP = "203.0.113.9"


@pytest.fixture(autouse=True)
def _clean():
    throttle.reset()
    yield
    throttle.reset()


# ---- one account being guessed at ---------------------------------------

async def test_a_few_wrong_passwords_are_tolerated():
    """People genuinely forget which password they used."""
    for _ in range(throttle.MAX_PER_EMAIL - 1):
        throttle.record_failure(EMAIL, IP)
    allowed, _ = throttle.check(EMAIL, IP)
    assert allowed


async def test_persistent_guessing_is_stopped():
    for _ in range(throttle.MAX_PER_EMAIL):
        throttle.record_failure(EMAIL, IP)
    allowed, wait = throttle.check(EMAIL, IP)
    assert allowed is False
    assert wait > 0


async def test_the_lockout_always_expires():
    """A permanent one would be a way to deny a real RM their job."""
    for _ in range(throttle.MAX_PER_EMAIL):
        throttle.record_failure(EMAIL, IP)
    _, wait = throttle.check(EMAIL, IP)
    assert 0 < wait <= throttle.LOCKOUT_SECONDS


async def test_getting_it_right_clears_the_count():
    """A near-miss must not cost somebody their next attempt."""
    for _ in range(throttle.MAX_PER_EMAIL - 1):
        throttle.record_failure(EMAIL, IP)
    throttle.record_success(EMAIL, IP)
    for _ in range(throttle.MAX_PER_EMAIL - 1):
        throttle.record_failure(EMAIL, IP)
    assert throttle.check(EMAIL, IP)[0]


async def test_an_account_is_guarded_however_the_source_changes():
    """Rotating addresses must not reset the count on one account."""
    for n in range(throttle.MAX_PER_EMAIL):
        throttle.record_failure(EMAIL, f"198.51.100.{n}")
    assert throttle.check(EMAIL, "198.51.100.200")[0] is False


# ---- one source spraying many accounts ----------------------------------

async def test_spraying_one_password_across_accounts_is_stopped():
    for n in range(throttle.MAX_PER_ADDRESS):
        throttle.record_failure(f"person{n}@eko.co.in", IP)
    assert throttle.check("someone.new@eko.co.in", IP)[0] is False


async def test_another_source_is_unaffected():
    """One attacker must not lock everybody else out."""
    for n in range(throttle.MAX_PER_ADDRESS):
        throttle.record_failure(f"person{n}@eko.co.in", IP)
    assert throttle.check("innocent@eko.co.in", "198.51.100.77")[0] is True


async def test_matching_an_email_ignores_case():
    for _ in range(throttle.MAX_PER_EMAIL):
        throttle.record_failure("Someone@Eko.co.in", IP)
    assert throttle.check("someone@eko.co.in", IP)[0] is False


# ---- through the API ----------------------------------------------------

async def test_the_login_endpoint_refuses_after_repeated_failures(client):
    """Verified against the real endpoint, not just the counter."""
    body = {"email": "nobody.here@eko.co.in", "password": "wrong"}

    seen = set()
    for _ in range(throttle.MAX_PER_EMAIL + 3):
        seen.add((await client.post("/api/auth/login", json=body)).status_code)

    assert 401 in seen, "wrong passwords should be refused"
    assert 429 in seen, "guessing was never throttled"


async def test_the_refusal_says_how_long_to_wait(client):
    body = {"email": "another.nobody@eko.co.in", "password": "wrong"}
    last = None
    for _ in range(throttle.MAX_PER_EMAIL + 2):
        last = await client.post("/api/auth/login", json=body)

    assert last.status_code == 429
    detail = last.json()["detail"]
    assert "wait" in detail.lower()
    assert "Forgot password" in detail, (
        "somebody locked out needs to be told the way forward")
