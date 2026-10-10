"""
CSP DocMaker — slowing down password guessing

The login had no limit at all. A password and an OTP is a good design, but
the password check could be attempted as fast as requests could be sent,
which turns a weak password into a matter of time rather than luck.

Two counters, because they stop different attacks:

  per email     one account being guessed at, from anywhere. Stops a
                targeted attack even when the attacker rotates addresses.
  per address   many accounts being tried from one place. Stops someone
                spraying one common password across every known email.

A lockout is temporary and never permanent: locking an account out for
good would hand anyone a way to deny a real RM their job just by failing
to log in as them a few times.

Counted in memory. That is honest about what it is — good for one process,
and it needs Redis before this runs on more than one. An imperfect limit
is worth a great deal more than none, and this used to be none.
"""

import logging
import time
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# A person who has genuinely forgotten which password they used will try a
# handful of times. Someone guessing will try thousands.
MAX_PER_EMAIL = 8
MAX_PER_ADDRESS = 20
WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60

_failures: Dict[str, List[float]] = {}


def _key(kind: str, value: str) -> str:
    return f"{kind}:{(value or '').strip().lower()}"


def _recent(key: str, now: float) -> List[float]:
    return [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]


def check(email: str, address: str) -> Tuple[bool, int]:
    """May this attempt proceed? Returns (allowed, seconds to wait).

    Called BEFORE the password is verified, so a locked-out attacker is
    refused without the system doing the work of checking.
    """
    now = time.monotonic()
    for key, limit in ((_key("email", email), MAX_PER_EMAIL),
                       (_key("ip", address), MAX_PER_ADDRESS)):
        recent = _recent(key, now)
        if len(recent) >= limit:
            wait = int(LOCKOUT_SECONDS - (now - recent[0]))
            return False, max(wait, 1)
    return True, 0


def record_failure(email: str, address: str) -> None:
    """A wrong password. Counted against both the account and the source."""
    now = time.monotonic()
    for key in (_key("email", email), _key("ip", address)):
        _failures[key] = _recent(key, now) + [now]

    _prune(now)
    logger.info(
        "login_throttle: failed attempt for %s from %s (%d recent for this "
        "account)", email, address,
        len(_failures.get(_key("email", email), [])),
    )


def record_success(email: str, address: str) -> None:
    """A correct password clears the count, so a near-miss costs nothing."""
    _failures.pop(_key("email", email), None)
    _failures.pop(_key("ip", address), None)


def _prune(now: float) -> None:
    """Keep the table from growing without bound on a long-running process."""
    if len(_failures) <= 10_000:
        return
    for key in [k for k, v in _failures.items()
                if not v or now - v[-1] > WINDOW_SECONDS]:
        _failures.pop(key, None)


def reset() -> None:
    """For tests."""
    _failures.clear()
