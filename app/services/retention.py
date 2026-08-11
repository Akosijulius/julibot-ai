"""
Data retention — periodic purge of non-essential rows.

Sessions (login records) and daily usage aggregates are housekeeping, not user
content. This module prunes them after a configurable window so the database
does not grow forever. Conversation and message *content* is deliberately NOT
touched here — that is only removed on explicit account deletion.

A background loop (``retention_loop``) is started in the app lifespan so the
purge runs on its own without blocking startup or requests.
"""

import asyncio
from datetime import date, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.database import async_session_maker
from app.models.session import Session
from app.models.usage import UserUsage

logger = get_logger(__name__)


async def purge_expired_sessions(db: AsyncSession, retention_days: int) -> int:
    """
    Delete session rows that have been expired *or* revoked for longer than
    ``retention_days``. Returns the number of rows removed.

    An unrevoked session whose JWT has expired is safe to purge: the token
    itself carries its own ``exp`` and can no longer be used.
    """
    cutoff = utcnow() - timedelta(days=retention_days)
    result = await db.execute(
        delete(Session).where(
            or_(
                Session.expires_at < cutoff,
                Session.revoked_at < cutoff,
            )
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


async def purge_old_usage(db: AsyncSession, retention_days: int) -> int:
    """Delete daily usage aggregates older than ``retention_days`` days."""
    cutoff = date.today() - timedelta(days=retention_days)
    result = await db.execute(
        delete(UserUsage).where(UserUsage.usage_date < cutoff)
    )
    await db.commit()
    return int(result.rowcount or 0)


async def retention_loop(interval_minutes: int) -> None:
    """Run periodically until cancelled: purge expired sessions and old usage."""
    settings = get_settings()
    while True:
        try:
            async with async_session_maker() as db:
                sessions = await purge_expired_sessions(db, settings.session_retention_days)
                usage = await purge_old_usage(db, settings.usage_retention_days)
            if sessions or usage:
                logger.info("Retention purge: %d sessions, %d usage rows", sessions, usage)
        except asyncio.CancelledError:
            logger.info("Retention loop stopped")
            raise
        except Exception:
            logger.exception("Retention purge failed; will retry next interval")
        await asyncio.sleep(interval_minutes * 60)
