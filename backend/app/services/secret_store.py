"""
CSP DocMaker — the locked store for each workspace's passwords and keys
(PROJECT-REGISTER No. 210, Stage 3, TK-021)

A Super Admin types a password once (Setup → Connections). It is encrypted
here (Fernet: AES with a check that it was not altered) with a key made
from the server's APP_SECRET_KEY, kept in workspace_secrets, and only ever
decrypted on the server at the moment the app needs it. It is never sent
back to a screen, never logged, never put in the change history (which
says only "set" / "removed") and never accepted in the chat.

If APP_SECRET_KEY changes, stored secrets cannot be read any more: the app
logs an error and the Connections screen asks for them again — it never
falls back to someone else's key.
"""

import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SecretUnreadable(RuntimeError):
    pass


def _fernet():
    from cryptography.fernet import Fernet
    from app.config import get_settings
    secret = get_settings().server.app_secret_key or ""
    key = hashlib.sha256(("cspdocmaker-secrets:" + secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def lock(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def unlock(token: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise SecretUnreadable("a stored secret cannot be read with this "
                               "server's APP_SECRET_KEY — enter it again on "
                               "Setup → Connections") from e


def unlock_quietly(token: Optional[str], what: str) -> Optional[str]:
    """Decrypted value, or None (logged as an error, never the value)."""
    if not token:
        return None
    try:
        return unlock(token)
    except SecretUnreadable as e:
        logger.error("secret_store: %s: %s", what, e)
        return None
