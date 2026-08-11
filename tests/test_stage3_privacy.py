"""
Stage 3 tests: privacy — account deletion and data retention.

Verifies:
- DELETE /auth/me removes all owned data (conversations, messages, sessions,
  usage) and revokes the user's access.
- Guests cannot delete accounts.
- Retention purge removes only rows past their retention window.
"""

import secrets
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.time import utcnow
from app.models.conversation import Conversation, Message
from app.models.session import Session
from app.models.usage import UserUsage
from app.models.user import User
from app.schemas.conversation import ConversationCreate
from app.services.chat_service import ChatService
from app.services.retention import purge_expired_sessions, purge_old_usage


async def _count(db, model) -> int:
    result = await db.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_delete_account_removes_all_data(
    client, db_session, auth_headers, test_user
):
    """Account deletion purges every owned row and invalidates the token."""
    chat = ChatService(db_session)
    conv = await chat.create_conversation(
        test_user, ConversationCreate(title="My chats")
    )
    await chat.add_message(conv, role="user", content="hello")
    await chat.add_message(conv, role="assistant", content="hi")

    # Give the user a session row and a usage row too.
    db_session.add(
        Session(
            user_id=test_user.id,
            jti=secrets.token_urlsafe(24),
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(minutes=30),
        )
    )
    db_session.add(
        UserUsage(user_id=test_user.id, usage_date=utcnow().date(), request_count=1)
    )
    await db_session.commit()

    resp = await client.delete("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 204

    # Everything the user owned is gone.
    assert await _count(db_session, User) == 0
    assert await _count(db_session, Conversation) == 0
    assert await _count(db_session, Message) == 0
    assert await _count(db_session, Session) == 0
    assert await _count(db_session, UserUsage) == 0

    # The deleted user can no longer authenticate.
    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_guest_cannot_delete_account(client):
    """Guests have no account and cannot call the deletion endpoint."""
    resp = await client.delete("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_purge_expired_sessions(db_session, test_user):
    """Only sessions past the retention window are purged."""
    now = utcnow()
    old = now - timedelta(days=40)
    recent = now - timedelta(days=2)

    # Expired long ago → should be purged.
    db_session.add(
        Session(user_id=test_user.id, jti="expired-old", created_at=old, expires_at=old)
    )
    # Revoked recently → within window, should stay.
    recent_revoked = Session(
        user_id=test_user.id, jti="revoked-recent", created_at=recent, expires_at=now
    )
    recent_revoked.revoked_at = recent
    db_session.add(recent_revoked)
    # Active, unexpired → should stay.
    db_session.add(
        Session(user_id=test_user.id, jti="active", created_at=now, expires_at=now + timedelta(minutes=30))
    )
    await db_session.commit()

    removed = await purge_expired_sessions(db_session, retention_days=30)
    assert removed == 1

    remaining = list(
        (await db_session.execute(select(Session.jti))).scalars().all()
    )
    assert "expired-old" not in remaining
    assert set(remaining) == {"revoked-recent", "active"}


@pytest.mark.asyncio
async def test_purge_old_usage(db_session, test_user):
    """Only usage rows older than the retention window are purged."""
    db_session.add(
        UserUsage(user_id=test_user.id, usage_date=datetime(2020, 1, 1), request_count=5)
    )
    db_session.add(
        UserUsage(user_id=test_user.id, usage_date=datetime.today(), request_count=1)
    )
    await db_session.commit()

    removed = await purge_old_usage(db_session, retention_days=365)
    assert removed == 1

    remaining = (await db_session.execute(select(UserUsage))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].usage_date == datetime.today().date()
