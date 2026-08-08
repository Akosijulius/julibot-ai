"""
User schemas for request validation and response serialization.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


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

    class Config:
        from_attributes = True


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
