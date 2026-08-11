"""
Database connection and session management.

Provides async database engine and session handling using SQLAlchemy.

**Production note:** PostgreSQL (via asyncpg) is recommended for any deployment
beyond local development. The engine is configured with ``pool_pre_ping=True``
to automatically discard stale server-side connections, and pool sizing is
controlled by the ``DB_POOL_SIZE`` / ``DB_MAX_OVERFLOW`` environment variables
(ignored by SQLite).
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.core.config import get_settings

settings = get_settings()

# Handle different database backends
database_url = settings.database_url

# Convert to async driver URLs
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif database_url.startswith("sqlite://"):
    database_url = database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)

connect_args = {}
engine_kwargs = dict(
    echo=settings.debug,
    future=True,
    # Auto-test connections before use — prevents stale-connection errors
    # after idling or server restarts (both PostgreSQL and SQLite benefit).
    pool_pre_ping=True,
)

if database_url.startswith("sqlite"):
    # check_same_thread: required when SQLite is used across threads (uvicorn).
    # timeout: seconds to wait when the DB file is locked by another connection
    # (e.g. a background title-generation task running alongside a streaming
    # request). Without this, concurrent requests hit "database is locked"
    # almost immediately under load.
    connect_args = {"check_same_thread": False, "timeout": 30}
else:
    # PostgreSQL pool sizing — tune via env vars; sensible defaults.
    engine_kwargs["pool_size"] = settings.db_pool_size
    engine_kwargs["max_overflow"] = settings.db_max_overflow

engine = create_async_engine(
    database_url,
    connect_args=connect_args,
    **engine_kwargs,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session.

    Yields an async session. Callers (services/routes) are responsible for
    committing when they mutate data. On unhandled exceptions we roll back.
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
