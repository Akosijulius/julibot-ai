"""
User schemas for request validation and response serialization.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

# Max length for a profile photo data URL. Frontend resizes uploads to ~256px
# before sending, so this is generous while still guarding against huge payloads.
MAX_PROFILE_PHOTO_LENGTH = 1_000_000


class UserBase(BaseModel):
    """Base user schema with common fields."""

    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)


class UserCreate(UserBase):
    """Schema for user registration."""

    password: str = Field(..., min_length=8, max_length=100)
    confirm_password: str = Field(..., min_length=8, max_length=100)


class UserLogin(BaseModel):
    """Schema for user login. Accepts either the username or email."""

    login: str = Field(..., min_length=3, max_length=255)
    password: str


class GoogleLoginRequest(BaseModel):
    """Schema for Google OAuth sign-in."""

    id_token: str


class UserResponse(UserBase):
    """Schema for user data in responses."""

    id: int
    is_active: bool
    created_at: datetime
    user_type: str = "registered"
    display_name: Optional[str] = None
    profile_photo_url: Optional[str] = None

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    """Schema for updating profile fields (display name / profile photo)."""

    display_name: Optional[str] = Field(None, min_length=1, max_length=50)
    profile_photo_url: Optional[str] = None

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: Optional[str]) -> Optional[str]:
        """Trim display name; treat empty/whitespace-only as 'no change' (None)."""
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        return v

    @field_validator("profile_photo_url")
    @classmethod
    def validate_profile_photo(cls, v: Optional[str]) -> Optional[str]:
        """Only accept image data URLs within a size limit."""
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.startswith("data:image/"):
            raise ValueError("Profile photo must be an image data URL")
        if len(v) > MAX_PROFILE_PHOTO_LENGTH:
            raise ValueError("Profile photo is too large")
        return v


class UserUpdate(BaseModel):
    """Schema for updating user information."""

    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    password: Optional[str] = Field(None, min_length=8, max_length=100)


class Token(BaseModel):
    """Schema for JWT token response."""

    access_token: str
    token_type: str = "bearer"
    user: Optional[UserResponse] = None


class TokenData(BaseModel):
    """Schema for decoded token data."""

    user_id: Optional[int] = None
