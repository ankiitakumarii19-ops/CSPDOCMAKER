"""
CSP DocMaker — Log in with Google (No. 171)

The sign-in page asks Google (Google Identity Services) for an ID token: a
signed statement "this is <email>, checked by Google". The server checks the
signature, that it was issued for OUR Client ID and that Google verified the
address. That check stands in for the emailed code: Google has already
proved the person owns the mailbox.

Who may enter does not change. The address must already have an account, or
be allowed one by the same rules as "Create Account" — added in the app to a
workspace, or listed in the Authorization sheet (SuperAdmins, Admins, RMs
tabs). The same email is the same account: signing in with Google never
makes a second one. Creating a NEW workspace still goes through
"Create Account".

Only GOOGLE_CLIENT_ID is needed: no client secret and no redirect address,
because the token comes back to the page itself, not through a redirect.
"""

import asyncio
import logging
import secrets
from typing import Optional, Tuple

from app.config import get_settings
from app.models.enums import AccountStatus, UserRole
from app.services import auth_service, google_sheets_service, workspace_service

logger = logging.getLogger(__name__)


class GoogleLoginError(Exception):
    """Sign-in refused, with a message fit to show the person."""

    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def enabled() -> bool:
    return bool(get_settings().google_client_id.strip())


def _verify_sync(credential: str, client_id: str) -> dict:
    # Imported here so a server without the Google button never loads them.
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(
        credential, google_requests.Request(), client_id)


async def verify(credential: str) -> Tuple[str, str]:
    """(email, name) from a Google ID token, or GoogleLoginError.

    verify_oauth2_token checks the signature against Google's published
    keys, the expiry, the issuer and that the token was made for our Client
    ID. It fetches the keys over the network, so it runs off the event loop.
    """
    client_id = get_settings().google_client_id.strip()
    if not client_id:
        raise GoogleLoginError("Log in with Google is not set up on this "
                               "server.", status_code=404)
    if not credential:
        raise GoogleLoginError("Google did not send a sign-in. Please try "
                               "again.", status_code=400)
    try:
        claims = await asyncio.to_thread(_verify_sync, credential, client_id)
    except ValueError as e:
        # Bad signature, expired, or made for another app.
        logger.warning("google_login.verify: token refused: %s", e)
        raise GoogleLoginError("The Google sign-in could not be checked. "
                               "Please try again.")
    except Exception as e:
        logger.error("google_login.verify: could not reach Google to check "
                     "the sign-in: %s: %s", type(e).__name__, e,
                     exc_info=True)
        raise GoogleLoginError("Google could not be reached to check the "
                               "sign-in. Please try again shortly.",
                               status_code=502)

    email = (claims.get("email") or "").strip().lower()
    if not email or not claims.get("email_verified"):
        logger.warning("google_login.verify: Google has not verified the "
                       "address %r", email)
        raise GoogleLoginError("Google has not verified this email address, "
                               "so it cannot be used to sign in.")
    name = (claims.get("name") or "").strip() or email.split("@")[0]
    return email, name


async def _role_for_new_account(db, email: str) -> Optional[str]:
    """The role "Create Account" would give this address, or None.

    Added in the app first (rm / admin, as signup_user's path c), then the
    Authorization sheet, highest role first.
    """
    for member, _ws in await workspace_service.memberships(db, email):
        if member.role in (UserRole.RM, UserRole.ADMIN):
            return member.role.value
    for role in ("super_admin", "admin", "rm"):
        try:
            listed, _row = google_sheets_service.check_authorization(
                email, role)
        except RuntimeError as e:
            logger.error("google_login: Authorization sheet check failed for "
                         "%s: %s", email, e)
            raise GoogleLoginError(
                "Who may sign in cannot be checked right now. Please try "
                "again later.", status_code=503)
        if listed:
            return role
    return None


async def _existing(db, email: str):
    """The account with this address in any capitals: an account made as
    "Ankita.Kumari@eko.co.in" is the same person as Google's lower-case
    "ankita.kumari@eko.co.in"."""
    from sqlalchemy import func, select

    from app.models.user import User
    from app.workspace_context import all_workspaces

    with all_workspaces():
        rows = (await db.execute(
            select(User).where(func.lower(User.email) == email)
        )).scalars().all()
    if len(rows) > 1:
        logger.error("google_login: %d accounts share the address %s in "
                     "different capitals", len(rows), email)
        raise GoogleLoginError("More than one account uses this email. "
                               "Please sign in with your password.",
                               status_code=409)
    return rows[0] if rows else None


async def user_for(db, email: str, name: str):
    """The account for this Google address: the existing one, or a new one
    if the address is allowed one. Never a duplicate."""
    user = await _existing(db, email)
    if user is None:
        role = await _role_for_new_account(db, email)
        if role is None:
            logger.info("google_login: %s has no account and is not on the "
                        "sign-in list", email)
            raise GoogleLoginError(
                f"{email} has not been added to CSP DocMaker. Please ask a "
                f"Super Admin to add you.", status_code=403)
        # A password nobody knows: the account works with Google, and
        # "Forgot password" sets a real one if the person ever wants it.
        ok, message, user = await auth_service.signup_user(
            db=db, email=email, name=name,
            password=secrets.token_urlsafe(32),
            requested_role=role, workspace_name=None)
        if not ok:
            raise GoogleLoginError(message, status_code=403)
        logger.info("google_login: account created for %s as %s", email, role)

    if user.account_status == AccountStatus.SUSPENDED:
        raise GoogleLoginError("Your account has been suspended. Contact "
                               "your administrator.", status_code=403)
    if user.account_status == AccountStatus.REVOKED:
        raise GoogleLoginError("Your account access has been revoked. "
                               "Contact your administrator.", status_code=403)
    return user
