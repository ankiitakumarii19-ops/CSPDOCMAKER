"""
CSP DocMaker — JWT Service

Handles JWT access/refresh token creation and verification.
Uses python-jose for token operations with HS256 signing.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token.

    Args:
        data: Payload dict — must include 'sub' (user email).
        expires_delta: Custom expiry. Defaults to config value.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    to_encode.update({"exp": expire, "type": "access"})
    try:
        return jwt.encode(
            to_encode,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
    except Exception as e:
        logger.error(
            "jwt_service.create_access_token failed: %s: %s",
            type(e).__name__, e,
        )
        raise


def create_refresh_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT refresh token with longer expiry."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(days=settings.jwt_refresh_token_expire_days)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    try:
        return jwt.encode(
            to_encode,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
    except Exception as e:
        logger.error(
            "jwt_service.create_refresh_token failed: %s: %s",
            type(e).__name__, e,
        )
        raise


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token.

    Returns:
        Decoded payload dict, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        logger.debug("jwt_service.decode_token failed: %s: %s", type(e).__name__, e)
        return None
    except Exception as e:
        logger.error(
            "jwt_service.decode_token unexpected error: %s: %s",
            type(e).__name__, e,
        )
        return None


def verify_access_token(token: str) -> Optional[dict]:
    """Verify an access token and return its payload.

    Returns:
        Payload dict with 'sub', 'role', etc. or None if invalid.
    """
    payload = decode_token(token)
    if payload is None:
        return None
    if payload.get("type") != "access":
        logger.debug("jwt_service.verify_access_token: token type is not 'access'")
        return None
    if "sub" not in payload:
        logger.debug("jwt_service.verify_access_token: 'sub' claim missing")
        return None
    return payload
