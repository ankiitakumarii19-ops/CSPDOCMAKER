"""
CSP DocMaker — Authentication Schemas

Pydantic models for authentication request/response validation.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from app.models.enums import UserRole


class SignupRequest(BaseModel):
    """Account creation request."""
    email: EmailStr = Field(..., description="Must be an @eko.co.in email")
    name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    requested_role: UserRole = Field(..., description="Role requested — backend verifies against Google Sheet")
    # Only for a Super Admin creating their own workspace.
    workspace_name: Optional[str] = Field(None, max_length=100)


class SignupResponse(BaseModel):
    """Account creation response."""
    message: str
    otp_sent: bool


class LoginRequest(BaseModel):
    """Login request. The OTP always goes to the account's email address."""
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Login response — returns tokens after OTP verification."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: UserRole
    name: str


class OTPSendRequest(BaseModel):
    """Request a fresh OTP. It is always sent by email."""
    email: EmailStr


class ResendOTPRequest(BaseModel):
    """Ask for a fresh code, because the last one expired or never arrived."""
    email: EmailStr


class WorkspaceChoice(BaseModel):
    """One workspace a person may enter, as shown on the chooser."""
    id: str
    name: str
    role: UserRole


class WorkspaceSelectRequest(BaseModel):
    selection_token: str
    workspace_id: str


class OTPVerifyRequest(BaseModel):
    """OTP verification request."""
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)


class OTPVerifyResponse(BaseModel):
    """OTP verification response."""
    verified: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    role: Optional[UserRole] = None
    name: Optional[str] = None
    workspace_id: Optional[str] = None
    workspace_name: Optional[str] = None
    # Set instead of the tokens when the person belongs to more than one
    # workspace: they choose, then exchange selection_token for real tokens.
    choose_workspace: bool = False
    workspaces: Optional[list[WorkspaceChoice]] = None
    selection_token: Optional[str] = None


class PasswordResetRequest(BaseModel):
    """Ask for a reset code. Answered the same way whether or not the
    address has an account, so this cannot be used to discover who does."""
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """The code from the email, plus the new password."""
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordResetResponse(BaseModel):
    message: str
