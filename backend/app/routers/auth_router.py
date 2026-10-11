"""
CSP DocMaker — Authentication Router

API endpoints for user authentication:
  GET  /api/auth/config      — Which email domains may sign in
  POST /api/auth/signup      — Create account (requires Google Sheet authorization)
  POST /api/auth/login       — Authenticate with email + password → sends OTP
  POST /api/auth/verify-otp  — Verify OTP → returns JWT tokens
  POST /api/auth/logout      — Invalidate session (client-side)
  POST /api/auth/forgot-password — Email a reset code
  POST /api/auth/reset-password  — Verify the code and set a new password
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import get_settings
from app.schemas.auth import (
    ResendOTPRequest,
    SignupRequest,
    SignupResponse,
    LoginRequest,
    OTPVerifyRequest,
    OTPVerifyResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetResponse,
    WorkspaceChoice,
    WorkspaceSelectRequest,
)
from app.models.enums import AccountStatus, UserRole
from app.models.workspace_member import WorkspaceMember
from app.services import workspace_service
from app.services import auth_service, jwt_service, otp_service
from app.services import login_throttle
from app.services import email_service
from app.services import login_history

logger = logging.getLogger(__name__)

settings = get_settings()

router = APIRouter()


@router.get("/config", summary="Public sign-in rules")
async def auth_config():
    """What the sign-in screen needs to know before anyone is logged in.

    The allowed domains live in one place — the server — so the form and
    the check behind it cannot disagree. This is deliberately public: it
    reveals nothing that the error message would not already say.
    """
    return {
        "allowed_email_domains": list(settings.allowed_email_domains),
        "allowed_email_domains_text": settings.allowed_email_domains_text,
    }


@router.post("/signup", response_model=SignupResponse)
async def signup(request: SignupRequest, db: AsyncSession = Depends(get_db)):
    """Create a new user account.

    1. Validates email domain (@eko.co.in)
    2. Checks Google Sheet authorization for the requested role
    3. Creates user record in DB
    4. Generates and delivers OTP
    """
    try:
        success, message, user = await auth_service.signup_user(
            db=db,
            email=request.email,
            name=request.name,
            password=request.password,
            requested_role=request.requested_role.value,
            workspace_name=request.workspace_name,
        )
    except Exception as e:
        logger.error(
            "auth_router.signup: unexpected error during signup for %s: %s: %s",
            request.email, type(e).__name__, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account creation failed due to a server error. Please try again.",
        )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    # Generate OTP
    try:
        otp_code, otp_ok = otp_service.generate_otp(request.email)
        if not otp_ok:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP requests. Please wait a minute and try again.",
            )
    except RuntimeError as e:
        logger.error(
            "auth_router.signup: OTP generation failed for %s: %s",
            request.email, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OTP generation failed. Please try again.",
        )

    delivery_ok = email_service.send_otp_email(
        to_email=request.email, otp_code=otp_code, user_name=request.name,
    )

    if not delivery_ok:
        logger.error(
            "auth_router.signup: OTP delivery failed for %s", request.email)

    return SignupResponse(
        message="Account created. An OTP has been emailed to you.",
        otp_sent=delivery_ok,
    )


@router.post("/login")
async def login(
    request: LoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with email and password, then send OTP.

    1. Verifies credentials
    2. Generates OTP
    3. Returns success message (tokens come after OTP verification)
    """
    # Before the password is even checked. A password plus an OTP is a
    # good design, but an unlimited password check turns a weak password
    # into a matter of time rather than luck.
    source = http_request.client.host if http_request.client else "unknown"
    allowed, wait = login_throttle.check(request.email, source)
    if not allowed:
        logger.warning(
            "auth_router.login: too many failed attempts for %s from %s",
            request.email, source,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many failed sign-in attempts. Please wait about "
                f"{max(wait // 60, 1)} minute(s) and try again, or use "
                f"Forgot password."
            ),
        )

    try:
        success, message, user = await auth_service.login_user(
            db=db,
            email=request.email,
            password=request.password,
        )
    except Exception as e:
        logger.error(
            "auth_router.login: unexpected error during login for %s: %s: %s",
            request.email, type(e).__name__, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed due to a server error. Please try again.",
        )

    if not success:
        login_throttle.record_failure(request.email, source)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
        )

    # The password was right. Clear the count so a near-miss costs nothing.
    login_throttle.record_success(request.email, source)

    # Generate OTP
    try:
        otp_code, otp_ok = otp_service.generate_otp(request.email)
        if not otp_ok:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP requests. Please wait a minute and try again.",
            )
    except RuntimeError as e:
        logger.error(
            "auth_router.login: OTP generation failed for %s: %s",
            request.email, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OTP generation failed. Please try again.",
        )

    delivery_ok = email_service.send_otp_email(
        to_email=request.email,
        otp_code=otp_code,
        user_name=user.name if user else None,
    )

    if not delivery_ok:
        logger.error(
            "auth_router.login: OTP delivery failed for %s", request.email)

    return {
        "message": "OTP sent. Please verify to complete login.",
        "otp_delivered": delivery_ok,
    }


@router.post("/verify-otp", response_model=OTPVerifyResponse)
async def verify_otp(request: OTPVerifyRequest, http_request: Request,
                     db: AsyncSession = Depends(get_db)):
    """Verify OTP and issue JWT tokens.

    1. Verifies the OTP code
    2. Activates user account if pending
    3. Issues access + refresh tokens
    """
    # Verify OTP
    verified, error_msg = otp_service.verify_otp(request.email, request.otp)
    if not verified:
        return OTPVerifyResponse(
            verified=False,
        )

    # Get user from DB
    try:
        user = await auth_service.get_user_by_email(db, request.email)
    except Exception as e:
        logger.error(
            "auth_router.verify_otp: DB error fetching user %s: %s: %s",
            request.email, type(e).__name__, e,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification failed due to a server error.",
        )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please sign up first.",
        )

    # Activate account if pending
    if user.account_status == AccountStatus.PENDING:
        user.account_status = AccountStatus.ACTIVE
        logger.info(
            "auth_router.verify_otp: account activated for %s", request.email,
        )

    # Update last login, and write the sign-in down. The timestamp answers
    # "is this account in use"; the record answers "when, and how often",
    # which a single overwritten column never could.
    user.last_login_at = datetime.now(timezone.utc)
    await login_history.record_login(
        db, user,
        address=http_request.client.host if http_request.client else None)

    # Configuration decides who is a Super Admin OF EKO SBI KIOSK CSP, and
    # it is read at every login — so adding someone to the list, or removing
    # them, takes effect the next time they sign in. It says nothing about
    # any other workspace: a Super Admin who created their own workspace is
    # one there because they created it, not because of this list.
    eko = await workspace_service.eko_workspace(db)
    if eko is not None:
        eko_member = await workspace_service.membership(db, user.email, eko.id)
        listed = await workspace_service.sheet_super_admins(db)
        if listed is None:
            # The SuperAdmins tab has never been read: unknown, so change
            # nothing rather than demote anyone.
            pass
        elif user.email.lower() in listed:
            if eko_member is None:
                db.add(WorkspaceMember(
                    workspace_id=eko.id, email=user.email.lower(),
                    name=user.name, role=UserRole.SUPER_ADMIN, active=True))
            elif eko_member.role is not UserRole.SUPER_ADMIN:
                logger.info("auth_router.verify_otp: %s promoted to Super "
                            "Admin of Eko by the SuperAdmins tab", user.email)
                eko_member.role = UserRole.SUPER_ADMIN
        elif (eko_member is not None
              and eko_member.role is UserRole.SUPER_ADMIN
              and eko_member.added_by_email is None):
            # Taken off the list: they stop being one immediately. A Super
            # Admin who was ADDED in the app (added_by_email set) is not
            # governed by the list, so is left alone.
            logger.info("auth_router.verify_otp: %s is no longer in the "
                        "SuperAdmins tab — demoted to Admin in Eko",
                        user.email)
            eko_member.role = UserRole.ADMIN
        await db.flush()

    if (user.workspace_id is not None
            and not await workspace_service.has_any_membership(
                db, user.email)):
        # An account older than memberships. Removed people still have an
        # (inactive) row, so this can never bring someone back.
        db.add(WorkspaceMember(
            workspace_id=user.workspace_id, email=user.email.lower(),
            name=user.name, role=user.role, active=True))
        await db.flush()

    choices = await workspace_service.memberships(db, user.email)
    if not choices:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of any workspace. Please ask a "
                   "Super Admin to add you.",
        )
    await db.commit()

    if len(choices) > 1:
        # Asked every time, as agreed: no workspace is assumed.
        return OTPVerifyResponse(
            verified=True,
            name=user.name,
            choose_workspace=True,
            workspaces=[WorkspaceChoice(id=str(ws.id), name=ws.name,
                                        role=m.role) for m, ws in choices],
            selection_token=jwt_service.create_selection_token(user.email),
        )

    member, ws = choices[0]
    return _issue_tokens(user, member, ws)


def _issue_tokens(user, member, ws) -> OTPVerifyResponse:
    """Real tokens, bound to one workspace and the role held there."""
    token_data = {
        "sub": user.email,
        "role": member.role.value,
        "name": user.name,
        "ws": str(ws.id),
    }
    logger.info("auth_router: tokens issued for %s in %s (role=%s)",
                user.email, ws.slug, member.role.value)
    return OTPVerifyResponse(
        verified=True,
        access_token=jwt_service.create_access_token(token_data),
        refresh_token=jwt_service.create_refresh_token(token_data),
        role=member.role,
        name=user.name,
        workspace_id=str(ws.id),
        workspace_name=ws.name,
    )


@router.post("/select-workspace", response_model=OTPVerifyResponse)
async def select_workspace(request: WorkspaceSelectRequest,
                           db: AsyncSession = Depends(get_db)):
    """Second half of signing in for someone in several workspaces."""
    email = jwt_service.verify_selection_token(request.selection_token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This sign-in has expired. Please log in again.",
        )
    member = await workspace_service.membership(db, email,
                                                request.workspace_id)
    if member is None:
        # Same answer whether the workspace does not exist or is not theirs.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of that workspace.",
        )
    user = await auth_service.get_user_by_email(db, email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Please log in again.")
    ws = next(w for m, w in await workspace_service.memberships(db, email)
              if m.id == member.id)
    return _issue_tokens(user, member, ws)


@router.post("/resend-otp")
async def resend_otp(
    request: ResendOTPRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a fresh code to someone part-way through signing in.

    A code expires after a few minutes, and an email can simply not
    arrive. Without this the only way forward is to enter the password
    again, which is a poor answer to "it expired".

    Two things this deliberately does NOT do:

      * It does not say whether the address has an account. The answer is
        the same either way, so this cannot be used to find out who is
        registered.
      * It does not bypass the rate limit. generate_otp already refuses
        more than a few codes a minute, and that limit is what stops this
        being a way to flood somebody's inbox.
    """
    settings_now = get_settings()
    generic = {
        "message": (
            f"If that account exists, a new code is on its way. It is valid "
            f"for {settings_now.otp_expiry_seconds // 60} minutes."
        )
    }

    if not settings_now.email_domain_allowed(request.email):
        return generic

    user = await auth_service.get_user_by_email(db, request.email)
    if user is None:
        logger.info(
            "auth_router.resend_otp: asked for %s, which has no account",
            request.email,
        )
        return generic

    try:
        otp_code, allowed = otp_service.generate_otp(request.email)
    except RuntimeError as e:
        logger.error("auth_router.resend_otp: could not generate a code for "
                     "%s: %s", request.email, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not send a new code. Please try again.",
        )

    if not allowed:
        # Said plainly rather than hidden: the person is waiting for an
        # email and needs to know why one is not coming.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "You have asked for several codes in the last minute. "
                "Please wait a moment, then try again."
            ),
        )

    delivered = email_service.send_otp_email(
        to_email=request.email, otp_code=otp_code, user_name=user.name,
    )
    if not delivered:
        logger.error("auth_router.resend_otp: delivery failed for %s",
                     request.email)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The code could not be emailed. Please try again shortly.",
        )

    logger.info("auth_router.resend_otp: a fresh code was sent to %s",
                request.email)
    return generic


@router.post("/logout")
async def logout():
    """Logout — client should discard tokens.

    Server-side token invalidation would require a Redis blacklist.
    For now, the client clears its session storage.
    """
    return {"message": "Logged out successfully."}


# The same answer whichever address is asked about. Saying "no such account"
# would turn this endpoint into a way to find out who has one.
_RESET_SENT = ("If that address has an account, a reset code has been "
               "sent to it.")


@router.post("/forgot-password", response_model=PasswordResetResponse)
async def forgot_password(
    request: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
):
    """Email a password-reset code.

    The code is namespaced to the reset purpose, so requesting one neither
    invalidates nor satisfies a pending login OTP.
    """
    from sqlalchemy import select

    from app.models.user import User

    user = (await db.execute(
        select(User).where(User.email == request.email)
    )).scalar_one_or_none()

    if user is None or user.account_status != AccountStatus.ACTIVE:
        # Logged, not revealed: the caller gets the same reply either way.
        logger.info(
            "auth_router.forgot_password: no reset sent for %s (no active account)",
            request.email,
        )
        return PasswordResetResponse(message=_RESET_SENT)

    try:
        otp_code, otp_ok = otp_service.generate_otp(
            request.email, purpose=otp_service.PASSWORD_RESET)
    except RuntimeError as e:
        logger.error("auth_router.forgot_password: code generation failed "
                     "for %s: %s", request.email, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not start the password reset. Please try again.",
        )

    if not otp_ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many reset requests. Please wait a minute and try again.",
        )

    delivered = email_service.send_otp_email(
        to_email=request.email,
        otp_code=otp_code,
        user_name=user.name,
        subject="CSP DocMaker — Reset your password",
    )
    if not delivered:
        logger.error("auth_router.forgot_password: delivery failed for %s",
                     request.email)

    return PasswordResetResponse(message=_RESET_SENT)


@router.post("/reset-password", response_model=PasswordResetResponse)
async def reset_password(
    request: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
):
    """Verify the reset code and set the new password.

    Only a code issued for a reset is accepted — a login OTP will not do,
    because the two live under different keys.
    """
    from sqlalchemy import select

    from app.models.user import User

    verified, error = otp_service.verify_otp(
        request.email, request.otp, purpose=otp_service.PASSWORD_RESET)
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    user = (await db.execute(
        select(User).where(User.email == request.email)
    )).scalar_one_or_none()

    # The code was valid, so the account existed when it was issued. If it is
    # gone or suspended now, the reset stops here rather than resurrecting it.
    if user is None or user.account_status != AccountStatus.ACTIVE:
        logger.warning(
            "auth_router.reset_password: valid code for %s but no active account",
            request.email,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account can no longer be reset. Contact an administrator.",
        )

    user.password_hash = auth_service.hash_password(request.new_password)
    await db.commit()

    logger.info("auth_router.reset_password: password changed for %s",
                request.email)
    return PasswordResetResponse(
        message="Your password has been changed. You can now log in.")
