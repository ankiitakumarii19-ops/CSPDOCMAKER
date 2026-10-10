"""
CSP DocMaker — Auth Service

Core authentication business logic:
- User signup with Google Sheet authorization check
- User login with password verification
- Password hashing and verification using bcrypt via passlib
"""

import logging
from typing import Optional, Tuple

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User
from app.workspace_context import all_workspaces
from app.models.enums import UserRole, AccountStatus
from app.services import google_sheets_service

logger = logging.getLogger(__name__)

settings = get_settings()

# Password hashing context — bcrypt with auto-deprecation support
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(
            "auth_service.verify_password: bcrypt verification failed: %s: %s",
            type(e).__name__, e,
        )
        return False


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Fetch a user by email from the database."""
    try:
        # An email is unique across ALL workspaces, and at sign-in nobody
        # has chosen a workspace yet — so this lookup is never filtered.
        with all_workspaces():
            result = await db.execute(select(User).where(User.email == email))
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(
            "auth_service.get_user_by_email: DB query failed for %s: %s: %s",
            email, type(e).__name__, e,
        )
        raise


async def _ensure_eko_member(db, email: str, name: str, role) -> None:
    """Make sure this person is a member of Eko SBI Kiosk CSP."""
    from app.models.workspace_member import WorkspaceMember
    from app.services import workspace_service

    eko = await workspace_service.eko_workspace(db)
    if eko is None:
        return
    if await workspace_service.membership(db, email, eko.id) is None:
        db.add(WorkspaceMember(
            workspace_id=eko.id, email=email.strip().lower(), name=name,
            role=role, active=True,
        ))
        await db.flush()


async def signup_user(
    db: AsyncSession,
    email: str,
    name: str,
    password: str,
    requested_role: str,
    workspace_name: Optional[str] = None,
) -> Tuple[bool, str, Optional[User]]:
    """Create a new user account after verifying Google Sheet authorization.

    Flow:
    1. Check email domain restriction
    2. Check if user already exists
    3. Verify authorization against Google Sheet (RM or Admin tab)
    4. Create user record in DB with hashed password

    Args:
        db: Database session.
        email: User email (must be on an allowed company domain).
        name: User full name.
        password: Plaintext password.
        requested_role: 'rm' or 'admin'.

    Returns:
        Tuple of (success, message, user).
    """
    # 1. Domain check
    if not settings.email_domain_allowed(email):
        return False, (
            f"Only {settings.allowed_email_domains_text} email addresses "
            f"are allowed."
        ), None

    # 2. Check if user already exists
    existing = await get_user_by_email(db, email)
    if existing:
        logger.info(
            "auth_service.signup_user: user already exists: %s (status=%s)",
            email, existing.account_status.value,
        )
        return False, "An account with this email already exists.", None

    # 3. Authorization. Four ways in, checked in this order.
    from app.services import workspace_service

    home_workspace_id = None   # None = the Eko workspace (the default)
    new_workspace_name = None
    invited = None
    authorized, sheet_data = False, None

    if settings.is_super_admin(email):
        # (a) A configured Super Admin runs Eko SBI Kiosk CSP, as before.
        requested_role = "super_admin"
        authorized = True
        logger.info(
            "auth_service.signup_user: %s is a configured Super Admin", email,
        )
    elif requested_role == "super_admin":
        # (b) Anyone on an allowed domain may create their OWN workspace.
        # It starts empty and sees nothing of any other workspace.
        problem = workspace_service.name_problem(workspace_name or "")
        if problem:
            return False, problem, None
        if await workspace_service.name_taken(db, workspace_name):
            return False, (
                "A workspace with that name already exists. Please choose "
                "another name."
            ), None
        new_workspace_name = workspace_service.clean_name(workspace_name)
        authorized = True
    else:
        # (c) A Super Admin added them in the app, to any workspace.
        for member, ws in await workspace_service.memberships(db, email):
            if member.role.value == requested_role:
                invited = (member, ws)
                break
        if invited:
            authorized = True
            home_workspace_id = invited[1].id
        else:
            # (d) Listed in Eko's Authorization sheet, exactly as before.
            try:
                authorized, sheet_data = (
                    google_sheets_service.check_authorization(
                        email, requested_role))
            except RuntimeError as e:
                logger.error(
                    "auth_service.signup_user: Google Sheets authorization "
                    "check failed for %s: %s", email, e,
                )
                return False, (
                    "Authorization verification is temporarily unavailable. "
                    "Please try again later or contact your administrator."
                ), None

    if not authorized:
        logger.info(
            "auth_service.signup_user: %s not authorized as %s",
            email, requested_role,
        )
        return False, (
            f"Your email ({email}) has not been added as '{requested_role}'. "
            f"Please ask a Super Admin to add you."
        ), None

    # 4. Get the mobile number from the sheet row. The authorization sheet
    # names this column 'Contact_no'.
    mobile = ""
    if sheet_data:
        mobile = google_sheets_service.get_field(
            sheet_data, "Contact_no", "Mobile", "Phone", "Mobile_no", "Contact",
        )

    # 5. Create user
    try:
        role = {
            "super_admin": UserRole.SUPER_ADMIN,
            "admin": UserRole.ADMIN,
        }.get(requested_role, UserRole.RM)
        user = User(
            email=email,
            name=name,
            mobile=mobile,
            role=role,
            account_status=AccountStatus.PENDING,
            password_hash=hash_password(password),
        )
        if new_workspace_name:
            ws = await workspace_service.create_workspace(
                db, new_workspace_name, email, name)
            home_workspace_id = ws.id
        if home_workspace_id is None:
            eko = await workspace_service.eko_workspace(db)
            home_workspace_id = eko.id if eko else None
        if home_workspace_id is not None:
            user.workspace_id = home_workspace_id
        with all_workspaces():
            db.add(user)
            await db.flush()  # Get the ID assigned without committing
            if not new_workspace_name and not invited:
                # Configured Super Admin or sheet-listed: a member of Eko.
                await _ensure_eko_member(db, email, name, role)

        logger.info(
            "auth_service.signup_user: user created: %s (role=%s, id=%s)",
            email, requested_role, user.id,
        )
        return True, "Account created successfully. Please verify your OTP.", user

    except Exception as e:
        logger.error(
            "auth_service.signup_user: DB insert failed for %s: %s: %s",
            email, type(e).__name__, e,
        )
        raise


async def login_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> Tuple[bool, str, Optional[User]]:
    """Authenticate a user with email and password.

    Flow:
    1. Check email domain
    2. Find user in DB
    3. Verify password
    4. Check account status

    Returns:
        Tuple of (success, message, user).
    """
    # 1. Domain check
    if not settings.email_domain_allowed(email):
        return False, (
            f"Only {settings.allowed_email_domains_text} email addresses "
            f"are allowed."
        ), None

    # 2. Find user
    user = await get_user_by_email(db, email)
    if not user:
        logger.info("auth_service.login_user: user not found: %s", email)
        return False, "Invalid email or password.", None

    # 3. Verify password
    if not verify_password(password, user.password_hash):
        logger.info("auth_service.login_user: invalid password for: %s", email)
        return False, "Invalid email or password.", None

    # 4. Check account status
    if user.account_status == AccountStatus.SUSPENDED:
        return False, "Your account has been suspended. Contact your administrator.", None
    if user.account_status == AccountStatus.REVOKED:
        return False, "Your account access has been revoked. Contact your administrator.", None

    logger.info(
        "auth_service.login_user: password verified for %s (role=%s, status=%s)",
        email, user.role.value, user.account_status.value,
    )
    return True, "Password verified. OTP required.", user
