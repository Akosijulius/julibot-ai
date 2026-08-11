"""
Stage 2 tests: DB optimization, pagination, and migration metadata.

Verifies:
- ``message_limit`` actually bounds the number of messages loaded.
- ``X-Total-Count`` pagination header is returned on the list endpoint.
- ``skip``/``limit`` pagination works without breaking the array response.
- Composite DB indexes are declared in the models.
"""

import pytest
from httpx import AsyncClient

from app.models.conversation import Conversation, Message
from app.schemas.conversation import ConversationCreate
from app.services.chat_service import ChatService


@pytest.mark.asyncio
async def test_list_conversations_pagination_header(client: AsyncClient, auth_headers):
    """List endpoint exposes total count via X-Total-Count header."""
    for title in ["A", "B", "C"]:
        await client.post(
            "/api/conversations/",
            headers=auth_headers,
            json={"title": title},
        )

    response = await client.get(
        "/api/conversations/",
        headers=auth_headers,
        params={"skip": 1, "limit": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)  # backward-compatible array shape preserved
    assert len(data) == 1
    assert response.headers.get("X-Total-Count") == "3"


@pytest.mark.asyncio
async def test_message_limit_bounds_get(client, db_session, auth_headers, test_user):
    """GET with a message_limit returns only the most recent N messages."""
    from datetime import timedelta

    from app.core.time import utcnow

    chat_service = ChatService(db_session)
    conv = await chat_service.create_conversation(
        test_user, ConversationCreate(title="Long chat")
    )

    # Insert 12 messages with strictly increasing created_at so ordering is
    # deterministic regardless of clock resolution.
    base = utcnow()
    for i in range(12):
        msg = Message(
            conversation_id=conv.id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"m{i}",
            created_at=base + timedelta(microseconds=i),
        )
        db_session.add(msg)
    await db_session.commit()

    response = await client.get(
        f"/api/conversations/{conv.id}",
        headers=auth_headers,
        params={"message_limit": 5},
    )
    assert response.status_code == 200
    messages = response.json().get("messages", [])
    assert len(messages) == 5
    # The 5 most recent messages, in chronological order.
    contents = [m["content"] for m in messages]
    assert contents == ["m7", "m8", "m9", "m10", "m11"]


@pytest.mark.asyncio
async def test_default_message_limit_is_100(client, db_session, auth_headers, test_user):
    """Default GET message_limit is 100, so loading stays bounded."""
    from app.core.config import get_settings
    assert get_settings().max_history_messages == 20

    chat_service = ChatService(db_session)
    conv = await chat_service.create_conversation(
        test_user, ConversationCreate(title="Many")
    )
    for i in range(150):
        await chat_service.add_message(conv, role="user", content=f"u{i}")

    response = await client.get(
        f"/api/conversations/{conv.id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    # No message_limit passed → default 100. A buggy unbounded loader would
    # return all 150; the bounded loader returns exactly 100.
    assert len(response.json().get("messages", [])) == 100


@pytest.mark.asyncio
async def test_composite_indexes_declared():
    """Conversation and Message models declare the composite DB indexes."""
    conv_idx = {i.name for i in Conversation.__table__.indexes}
    msg_idx = {i.name for i in Message.__table__.indexes}
    # Composite indexes.
    assert "ix_conversations_user_updated" in conv_idx
    assert "ix_messages_conversation_created" in msg_idx
    # Single-column FK indexes (from index=True on the column).
    assert "ix_conversations_user_id" in conv_idx
    assert "ix_messages_conversation_id" in msg_idx
