"""
Authentication dependencies for protecting routes.

Provides dependencies for extracting and validating JWT tokens from requests.
Supports both registered users and optional guest access.
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.database import get_db
from app.models.user import User

# HTTP Bearer token scheme — auto_error=False lets us handle missing tokens ourselves
security_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency that extracts and validates the current user from a JWT token.

    If no token is provided or the token is invalid, returns a guest user
    with user_type='guest'. This allows both authenticated and guest users
    to access the same endpoints.

    Returns:
        User: The authenticated user, or a guest User object
    """
    # No token → return a guest user (no DB entry)
    if not credentials or not credentials.credentials:
        return User(
            id=0,
            email="guest@julibot.local",
            username="Guest",
            hashed_password="",
            is_active=True,
            user_type="guest",
        )

    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        # Invalid token → guest
        return User(
            id=0,
            email="guest@julibot.local",
            username="Guest",
            hashed_password="",
            is_active=True,
            user_type="guest",
        )

    raw_sub = payload.get("sub")
    if raw_sub is None:
        return User(
            id=0,
            email="guest@julibot.local",
            username="Guest",
            hashed_password="",
            is_active=True,
            user_type="guest",
        )

    try:
        user_id = int(raw_sub)
    except (TypeError, ValueError):
        return User(
            id=0,
            email="guest@julibot.local",
            username="Guest",
            hashed_password="",
            is_active=True,
            user_type="guest",
        )

    # Query user from database
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        return User(
            id=0,
            email="guest@julibot.local",
            username="Guest",
            hashed_password="",
            is_active=True,
            user_type="guest",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return user


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Strict dependency: requires a valid JWT token. No guest fallback.

    Use this for endpoints that MUST have a real user (e.g. register, login).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise credentials_exception

    raw_sub = payload.get("sub")
    if raw_sub is None:
        raise credentials_exception

    try:
        user_id = int(raw_sub)
    except (TypeError, ValueError):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency that ensures the current user is active.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user
