"""
Database connection and session management.

Provides async database engine and session handling using SQLAlchemy.
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
if database_url.startswith("sqlite"):
    # Required for SQLite when used across threads (e.g. under uvicorn)
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    database_url,
    echo=settings.debug,
    future=True,
    connect_args=connect_args,
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
