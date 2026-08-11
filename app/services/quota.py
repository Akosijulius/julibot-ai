"""
Per-user AI usage quotas.

Enforces configurable daily request and output-token limits for registered
users, backed by the `user_usage` table (aggregate counters only — no message
contents). This is the foundation for future plans (guest / free / pro).

Guests have no persistent row (id 0 is not a real user), so they are bounded
by per-IP rate limiting plus the hard per-response output cap rather than a
daily quota.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import RateLimitException
from app.core.time import utcnow
from app.models.usage import UserUsage

settings = get_settings()


def _today() -> date:
    return utcnow().date()


def _is_guest(user) -> bool:
    return getattr(user, "user_type", "registered") == "guest"


def _limits_for(user) -> tuple[int, int]:
    """Return (daily_request_limit, daily_output_token_limit) for a user."""
    if _is_guest(user):
        return settings.quota_guest_daily_requests, settings.quota_guest_daily_output_tokens
    return settings.quota_daily_requests, settings.quota_daily_output_tokens


async def _get_or_create(db: AsyncSession, user_id: int) -> UserUsage:
    """Fetch today's usage row for the user, creating it if needed."""
    result = await db.execute(
        select(UserUsage).where(
            UserUsage.user_id == user_id, UserUsage.usage_date == _today()
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserUsage(user_id=user_id, usage_date=_today())
        db.add(row)
        try:
            await db.flush()
        except IntegrityError:
            # Concurrent first-use-of-the-day race: re-fetch the row.
            await db.rollback()
            result = await db.execute(
                select(UserUsage).where(
                    UserUsage.user_id == user_id, UserUsage.usage_date == _today()
                )
            )
            row = result.scalar_one()
    return row


async def check_quota(db: AsyncSession, user) -> None:
    """Raise RateLimitException if the user has exceeded today's quota."""
    if not settings.quota_enabled or _is_guest(user):
        return
    req_limit, token_limit = _limits_for(user)
    row = await _get_or_create(db, user.id)
    if row.request_count >= req_limit:
        raise RateLimitException("Daily AI request quota exceeded", limit=req_limit)
    if row.output_tokens >= token_limit:
        raise RateLimitException("Daily AI token quota exceeded", limit=token_limit)


async def record_usage(
    db: AsyncSession,
    user,
    input_tokens: int = 0,
    output_tokens: int = 0,
    commit: bool = True,
) -> None:
    """Increment today's usage counters for the user."""
    if not settings.quota_enabled or _is_guest(user):
        return
    row = await _get_or_create(db, user.id)
    row.request_count += 1
    row.input_tokens += max(0, input_tokens or 0)
    row.output_tokens += max(0, output_tokens or 0)
    if commit:
        await db.commit()
