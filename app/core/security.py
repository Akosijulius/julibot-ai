"""
Security utilities for authentication and password management.

Handles password hashing, JWT token creation, and token validation.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext

from app.core.config import get_settings

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

settings = get_settings()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate a hash from a plain password."""
    return pwd_context.hash(password)


def create_access_token(
    data: dict[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Payload to encode in the token (usually user identifier)
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()

    # JWT "sub" must be a string per the JWT spec
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.access_token_expire_minutes
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.secret_key, algorithm=settings.algorithm
    )

    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """
    Decode and validate a JWT access token.

    Args:
        token: JWT token string to decode

    Returns:
        Decoded payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except InvalidTokenError:
        return None
