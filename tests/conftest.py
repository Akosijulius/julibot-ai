"""
Shared test fixtures and async test setup for JULIBOT.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.core.security import get_password_hash
from app.models.user import User


# In-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create isolated in-memory SQLite engine per test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncSession:
    """Provide a fresh database session for each test."""
    async_session = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """Provide an AsyncClient with overridden DB dependency."""
    from app.main import app
    from app.db.database import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def test_user(db_session: AsyncSession):
    """Create a test user and return it."""
    from datetime import datetime, timezone
    import secrets

    user = User(
        email=f"test_{secrets.token_hex(4)}@example.com",
        username=f"testuser_{secrets.token_hex(4)}",
        hashed_password=get_password_hash("testpassword123"),
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture(autouse=True)
def mock_ai_orchestrator(monkeypatch):
    """
    Patch the AI orchestrator so tests never call the real Gemini API.
    Keeps tests offline, fast, and deterministic.
    """
    from app.services.ai_orchestrator import AIOrchestrator
    from app.services.llm import StreamChunk, GenerateResponse

    async def fake_chat(self, context):
        """Fake chat that returns a mock response."""
        from app.services.ai_orchestrator import ChatResult
        from app.services.prompts import AssistantMode
        from app.services.context_manager import ContextWindow
        from app.services.llm import ChatMessage

        return ChatResult(
            content=f"Mock AI response to: {context.user_message}",
            model="mock-model",
            provider="mock",
            mode=context.mode,
            context_window=ContextWindow(messages=[ChatMessage(role="user", content=context.user_message)]),
        )

    async def fake_generate_stream(self, context):
        """Fake streaming that yields mock chunks."""
        yield StreamChunk(
            content=f"Mock AI response to: {context.user_message}",
            model="mock-model",
            provider="mock",
            is_final=True,
            finish_reason="stop",
        )

    async def fake_generate_title(self, first_message):
        """Fake title generation."""
        return "Mock Title"

    async def fake_is_available(self):
        """Fake availability check."""
        return True

    monkeypatch.setattr(AIOrchestrator, "chat", fake_chat)
    monkeypatch.setattr(AIOrchestrator, "chat_stream", fake_generate_stream)
    monkeypatch.setattr(AIOrchestrator, "generate_title", fake_generate_title)
    monkeypatch.setattr(AIOrchestrator, "is_available", fake_is_available)


@pytest_asyncio.fixture(scope="function")
async def auth_token(client: AsyncClient, test_user: User):
    """Return a JWT auth token for the test user."""
    from app.core.security import create_access_token

    token = create_access_token(data={"sub": str(test_user.id)})
    return token


@pytest_asyncio.fixture(scope="function")
async def auth_headers(auth_token: str):
    """Return Authorization header dict."""
    return {"Authorization": f"Bearer {auth_token}"}
