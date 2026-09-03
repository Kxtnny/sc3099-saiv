"""User and authentication schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.config import settings
from app.core.sanitize import sanitize_text
from app.enums import UserRole
from app.schemas.common import UTCDateTime


# =============================================================================
# Requests
# =============================================================================

class UserCreate(BaseModel):
    """
    Registration payload.

    Any role may be requested, including admin: there is no bootstrap account,
    so this is the only way the first admin can exist. The briefing explicitly
    says to ignore role restrictions during registration.
    """

    email: EmailStr
    password: str = Field(min_length=settings.MIN_PASSWORD_LENGTH, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.STUDENT

    @field_validator("full_name")
    @classmethod
    def clean_full_name(cls, value: str) -> str:
        cleaned = sanitize_text(value)
        if not cleaned:
            raise ValueError("full_name must contain readable characters")
        return cleaned


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserUpdate(BaseModel):
    """Self-service profile update (PUT /users/me)."""

    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    camera_consent: Optional[bool] = None
    geolocation_consent: Optional[bool] = None

    @field_validator("full_name")
    @classmethod
    def clean_full_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = sanitize_text(value)
        if not cleaned:
            raise ValueError("full_name must contain readable characters")
        return cleaned


class UserAdminUpdate(BaseModel):
    """Administrative update (PATCH /users/{user_id})."""

    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None

    @field_validator("full_name")
    @classmethod
    def clean_full_name(cls, value: Optional[str]) -> Optional[str]:
        return sanitize_text(value) if value else value


# =============================================================================
# Responses
# =============================================================================

class UserResponse(BaseModel):
    """
    Public user representation.

    Deliberately enumerates its fields: hashed_password must never be
    serialised, so this schema is an allow-list rather than a dump of the ORM
    object.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    camera_consent: bool
    geolocation_consent: bool
    face_enrolled: bool
    created_at: UTCDateTime
    updated_at: Optional[UTCDateTime] = None
    last_login_at: Optional[UTCDateTime] = None


class TokenResponse(BaseModel):
    """Login response. Tokens carry identity claims only, never secrets."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    user: UserResponse


class TokenRefreshResponse(BaseModel):
    """Refresh response - no user object, per the API specification."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
