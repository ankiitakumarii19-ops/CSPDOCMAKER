"""
CSP DocMaker — Auth Dependencies

FastAPI dependencies for JWT-based authentication and role-based access control.
Used with Depends() on protected route handlers.
"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services import jwt_service
from app.models.enums import UserRole

logger = logging.getLogger(__name__)

# Bearer token extractor — looks for "Authorization: Bearer <token>" header
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """Extract and validate the current user from the JWT access token.

    Returns:
        Dict with 'sub' (email), 'role', 'name' from the token payload.

    Raises:
        HTTPException 401 if token is missing, invalid, or expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = jwt_service.verify_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def require_rm(current_user: dict = Depends(get_current_user)) -> dict:
    """Require the current user to have the RM role."""
    if current_user.get("role") != UserRole.RM.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. This resource requires RM role.",
        )
    return current_user


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Require the current user to have the Admin role."""
    if current_user.get("role") != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. This resource requires Admin role.",
        )
    return current_user


async def require_any_role(current_user: dict = Depends(get_current_user)) -> dict:
    """Require any role this system recognises.

    SUPER_ADMIN is included deliberately. A Workspace Owner configures the
    system; locking them out of records an Admin can read would mean the
    person responsible for a workspace could see less of it than the people
    they appointed.
    """
    role = current_user.get("role")
    if role not in (UserRole.RM.value, UserRole.ADMIN.value,
                    UserRole.SUPER_ADMIN.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Valid role required.",
        )
    return current_user


def require_role(*allowed_roles: str):
    """Factory that returns a FastAPI dependency checking role membership.

    Usage:
        user=Depends(require_role("rm", "admin"))
    """
    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        role = current_user.get("role", "")
        # Normalise to uppercase for comparison against UserRole enum values
        if role.upper() not in [r.upper() for r in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of: {', '.join(allowed_roles)}.",
            )
        return current_user
    return _check
