"""
Authentication dependencies for protecting routes.

Single canonical mechanism:

    token extraction (Authorization: Bearer OR HttpOnly cookie)
        → JWT decode + server-side session check
        → active user resolution

Supports both registered users and the optional guest fallback. Tokens may
arrive via the ``Authorization`` header (API clients / tools) or the HttpOnly
cookie (browser). Tokens carrying a ``jti`` require a live, non-revoked
Session; jti-less tokens are validated statelessly for backward compatibility.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.database import get_db
from app.models.session import Session
from app.models.user import User
from app.services.auth_service import ACCESS_COOKIE

# HTTP Bearer token scheme — auto_error=False lets us handle missing tokens
# ourselves (a cookie may carry the token instead).
security_optional = HTTPBearer(auto_error=False)

GUEST_EMAIL = "guest@julibot.local"
GUEST_USERNAME = "Guest"


def _guest_user() -> User:
    """A synthetic, non-persisted guest user (id 0 never collides with real rows)."""
    return User(
        id=0,
        email=GUEST_EMAIL,
        username=GUEST_USERNAME,
        hashed_password="",
        is_active=True,
        user_type="guest",
    )


def _extract_token(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials]
) -> Optional[str]:
    """Return the access token from the Bearer header or HttpOnly cookie."""
    if credentials and credentials.credentials:
        return credentials.credentials
    return request.cookies.get(ACCESS_COOKIE)


def _payload_sub(payload: dict) -> Optional[int]:
    """Parse and validate the ``sub`` claim into a user id (or None)."""
    raw = payload.get("sub")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _resolve_active_user(
    db: AsyncSession, token: str, request: Request
) -> Optional[User]:
    """
    Decode the token, verify its server-side session (when a jti is present),
    and load the active user. Returns None when anything is invalid/revoked.
    """
    payload = decode_access_token(token)
    if payload is None:
        return None

    user_id = _payload_sub(payload)
    if user_id is None:
        return None

    # If the token is session-bound, require a live, non-revoked session.
    jti = payload.get("jti")
    if jti:
        result = await db.execute(select(Session).where(Session.jti == jti))
        session = result.scalar_one_or_none()
        if session is None or session.revoked_at is not None:
            return None
        request.state.jti = jti

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Extract and validate the current user from a JWT (header or cookie).

    If no valid token is provided, returns a guest user (user_type='guest').
    This allows both authenticated and guest users to share endpoints while
    guest access to protected features is gated explicitly at the route layer.
    """
    token = _extract_token(request, credentials)
    if not token:
        return _guest_user()

    user = await _resolve_active_user(db, token, request)
    if user is None:
        return _guest_user()
    return user


async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Strict dependency: requires a valid JWT token (header or cookie). No guest
    fallback. Use for endpoints that MUST have a real user (register, login,
    logout, profile, account deletion).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = _extract_token(request, credentials)
    if not token:
        raise credentials_exception

    user = await _resolve_active_user(db, token, request)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure the current user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user
