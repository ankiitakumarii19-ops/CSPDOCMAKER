"""
CSP DocMaker — OTP Service

Generates, stores (in Redis), and verifies one-time passwords.
Implements rate limiting and max-attempt protections.

OTPs are stored in Redis with automatic TTL expiry.
Key schema:
  otp:{email}        → hashed OTP value
  otp_attempts:{email} → attempt counter
  otp_rate:{email}   → rate limit counter (per-minute window)
"""

import hashlib
import logging
import secrets
from typing import Optional, Tuple

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Redis client — synchronous, used from Celery and API handlers
_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    """Get or create the Redis client for OTP storage."""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=0,
                decode_responses=True,
            )
            _redis_client.ping()
        except redis.ConnectionError as e:
            logger.error(
                "otp_service._get_redis: Redis connection failed: %s: %s",
                type(e).__name__, e,
            )
            raise RuntimeError(
                f"OTP service unavailable — Redis connection failed at "
                f"{settings.redis_host}:{settings.redis_port}: {e}"
            ) from e
    return _redis_client


def _hash_otp(otp: str) -> str:
    """Hash OTP for secure storage — never store plaintext."""
    return hashlib.sha256(otp.encode()).hexdigest()


LOGIN = "login"
PASSWORD_RESET = "password_reset"


def _keys(email: str, purpose: str):
    """Redis keys for one address and one purpose.

    Codes are namespaced by what they are for. Without this a password-reset
    code and a login code would share one key, so requesting either would
    silently invalidate the other — and a code issued for one purpose could
    be presented for the other. "login" keeps the original key names so
    existing codes stay valid across the change.
    """
    suffix = email if purpose == LOGIN else f"{purpose}:{email}"
    return f"otp:{suffix}", f"otp_attempts:{suffix}", f"otp_rate:{suffix}"


def generate_otp(email: str, purpose: str = LOGIN) -> Tuple[str, bool]:
    """Generate and store a new OTP for the given email.

    Args:
        email: The user's email address.

    Returns:
        Tuple of (otp_code, success). otp_code is the plaintext OTP
        to be delivered to the user. success is False if rate-limited.
    """
    r = _get_redis()
    otp_key, attempts_key, rate_key = _keys(email, purpose)

    # Rate limiting — max N OTP requests per minute
    try:
        current_rate = r.get(rate_key)
        if current_rate and int(current_rate) >= settings.otp_rate_limit_per_minute:
            logger.warning(
                "otp_service.generate_otp: rate limit exceeded for %s (limit=%d/min)",
                email, settings.otp_rate_limit_per_minute,
            )
            return "", False
    except (redis.RedisError, ValueError) as e:
        logger.error(
            "otp_service.generate_otp: rate limit check failed for %s: %s: %s",
            email, type(e).__name__, e,
        )
        # Fail open on rate-limit check errors — still generate OTP
        pass

    # Generate OTP
    otp_code = "".join(
        [str(secrets.randbelow(10)) for _ in range(settings.otp_length)]
    )

    try:
        pipe = r.pipeline()
        # Store hashed OTP with expiry
        pipe.set(otp_key, _hash_otp(otp_code), ex=settings.otp_expiry_seconds)
        # Reset attempts counter
        pipe.set(attempts_key, 0, ex=settings.otp_expiry_seconds)
        # Increment rate limiter (60-second window)
        pipe.incr(rate_key)
        pipe.expire(rate_key, 60)
        pipe.execute()
    except redis.RedisError as e:
        logger.error(
            "otp_service.generate_otp: Redis storage failed for %s: %s: %s",
            email, type(e).__name__, e,
        )
        raise RuntimeError(
            f"OTP generation failed — could not store OTP in Redis: {e}"
        ) from e

    logger.info("otp_service.generate_otp: OTP generated for %s", email)
    return otp_code, True


def verify_otp(email: str, otp_code: str,
               purpose: str = LOGIN) -> Tuple[bool, str]:
    """Verify an OTP for the given email.

    Args:
        email: The user's email address.
        otp_code: The OTP code to verify.

    Returns:
        Tuple of (verified, error_message).
        verified is True if the OTP matches.
        error_message describes why verification failed, or empty if success.
    """
    r = _get_redis()
    otp_key, attempts_key, _ = _keys(email, purpose)

    try:
        # Check if OTP exists (not expired)
        stored_hash = r.get(otp_key)
        if stored_hash is None:
            logger.info(
                "otp_service.verify_otp: no OTP found for %s (expired or never generated)",
                email,
            )
            return False, "OTP expired or not found. Please request a new OTP."

        # Check attempt count
        attempts = r.get(attempts_key)
        attempt_count = int(attempts) if attempts else 0
        if attempt_count >= settings.otp_max_attempts:
            # Invalidate OTP after max attempts
            r.delete(otp_key, attempts_key)
            logger.warning(
                "otp_service.verify_otp: max attempts exceeded for %s (attempts=%d)",
                email, attempt_count,
            )
            return False, "Maximum OTP attempts exceeded. Please request a new OTP."

        # Increment attempt counter
        r.incr(attempts_key)

        # Verify OTP
        if _hash_otp(otp_code) == stored_hash:
            # Success — clean up
            r.delete(otp_key, attempts_key)
            logger.info("otp_service.verify_otp: OTP verified for %s", email)
            return True, ""
        else:
            remaining = settings.otp_max_attempts - attempt_count - 1
            logger.info(
                "otp_service.verify_otp: invalid OTP for %s (remaining=%d)",
                email, remaining,
            )
            return False, f"Invalid OTP. {remaining} attempt(s) remaining."

    except redis.RedisError as e:
        logger.error(
            "otp_service.verify_otp: Redis error for %s: %s: %s",
            email, type(e).__name__, e,
        )
        return False, "OTP verification failed due to a server error. Please try again."
