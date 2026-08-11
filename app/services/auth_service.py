"""
Authentication service — the single canonical implementation for issuing,
validating, and revoking access-token sessions, plus HttpOnly cookie handling.

Keeping this in one place means there is exactly one way tokens are created,
one way they map to a server-side session, and one way they are invalidated.
"""

import secrets
from datetime import timedelta

from fastapi import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token
from app.core.time import utcnow
from app.models.session import Session
from app.models.user import User

# Name of the HttpOnly cookie that carries the access token.
ACCESS_COOKIE = "julibot_access"

settings = get_settings()


def cookie_max_age_seconds() -> int:
    """Cookie lifetime matches the token lifetime."""
    return settings.access_token_expire_minutes * 60


def set_access_cookie(response: Response, token: str) -> None:
    """
    Set the HttpOnly access-token cookie.

    - HttpOnly: JavaScript cannot read it (prevents XSS token theft).
    - Secure: only over HTTPS (production). In local http:// dev it must be
      off or browsers refuse to store it.
    - SameSite=Lax: cookies are sent on same-site requests and top-level
      navigations but NOT on cross-site subresource POSTs, giving baseline
      CSRF protection for state-changing requests.
    """
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=token,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
        max_age=cookie_max_age_seconds(),
    )


def clear_access_cookie(response: Response) -> None:
    """Expire and remove the access-token cookie."""
    response.delete_cookie(
        key=ACCESS_COOKIE,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/",
    )


async def issue_session(db: AsyncSession, user: User, request=None) -> tuple[str, Session]:
    """
    Create a JWT with a fresh ``jti`` and a matching server-side Session row.

    Returns (token, session). The token is only considered valid while the
    Session row exists and is not revoked.
    """
    jti = secrets.token_urlsafe(24)
    token = create_access_token(data={"sub": user.id}, jti=jti)

    now = utcnow()
    session = Session(
        user_id=user.id,
        jti=jti,
        created_at=now,
        expires_at=now + timedelta(minutes=settings.access_token_expire_minutes),
        user_agent=(request.headers.get("user-agent")[:255] if request and request.headers.get("user-agent") else None),
        ip_address=(request.client.host if request and request.client else None),
    )
    db.add(session)
    await db.commit()
    return token, session


async def get_active_session(db: AsyncSession, jti: str) -> Session | None:
    """Return an active (non-revoked) session for a jti, else None."""
    result = await db.execute(select(Session).where(Session.jti == jti))
    session = result.scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        return None
    return session


async def revoke_session(db: AsyncSession, jti: str) -> None:
    """Revoke a single session (logout)."""
    await db.execute(
        update(Session)
        .where(Session.jti == jti, Session.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await db.commit()


async def revoke_all_user_sessions(db: AsyncSession, user_id: int) -> None:
    """Revoke every session for a user (log out all devices)."""
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await db.commit()
