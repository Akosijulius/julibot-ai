"""
Tests for conversation and chat endpoints, including guest mode.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_conversation(client: AsyncClient, auth_headers):
    """Authenticated user can create a conversation."""
    response = await client.post(
        "/api/conversations/",
        headers=auth_headers,
        json={"title": "Test Conversation"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Conversation"
    assert "id" in data
    assert "messages" in data


@pytest.mark.asyncio
async def test_list_conversations_empty(client: AsyncClient, auth_headers):
    """Empty conversation list returns 200 with empty array."""
    response = await client.get("/api/conversations/", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_conversations_with_data(client: AsyncClient, auth_headers):
    """List returns created conversations."""
    for title in ["Conversation A", "Conversation B"]:
        await client.post(
            "/api/conversations/",
            headers=auth_headers,
            json={"title": title},
        )

    response = await client.get("/api/conversations/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    titles = {c["title"] for c in data}
    assert titles == {"Conversation A", "Conversation B"}


@pytest.mark.asyncio
async def test_get_conversation_not_found(client: AsyncClient, auth_headers):
    """Fetching a nonexistent conversation returns 404."""
    response = await client.get(
        "/api/conversations/99999",
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_conversation_title(client: AsyncClient, auth_headers):
    """Conversation title can be updated."""
    create_resp = await client.post(
        "/api/conversations/",
        headers=auth_headers,
        json={"title": "Original Title"},
    )
    conv_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/conversations/{conv_id}",
        headers=auth_headers,
        json={"title": "Updated Title"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_delete_conversation(client: AsyncClient, auth_headers):
    """Deleting a conversation returns 204 and removes it."""
    create_resp = await client.post(
        "/api/conversations/",
        headers=auth_headers,
        json={"title": "To Delete"},
    )
    conv_id = create_resp.json()["id"]

    delete_resp = await client.delete(
        f"/api/conversations/{conv_id}",
        headers=auth_headers,
    )
    assert delete_resp.status_code == 204

    get_resp = await client.get(
        f"/api/conversations/{conv_id}",
        headers=auth_headers,
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_chat_without_ai_key(client: AsyncClient, auth_headers):
    """Chat returns a graceful message when no API key is configured."""
    response = await client.post(
        "/api/conversations/chat",
        headers=auth_headers,
        json={"message": "Hello JULIBOT"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "conversation_id" in data


@pytest.mark.asyncio
async def test_chat_saves_messages(client: AsyncClient, auth_headers):
    """Chat creates a conversation and stores both user and assistant messages."""
    response = await client.post(
        "/api/conversations/chat",
        headers=auth_headers,
        json={"message": "What is JULIBOT?"},
    )
    assert response.status_code == 200
    conv_id = response.json()["conversation_id"]

    conv_resp = await client.get(
        f"/api/conversations/{conv_id}",
        headers=auth_headers,
    )
    assert conv_resp.status_code == 200
    messages = conv_resp.json().get("messages", [])
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_chat_with_existing_conversation(client: AsyncClient, auth_headers):
    """Chat can continue an existing conversation."""
    create_resp = await client.post(
        "/api/conversations/",
        headers=auth_headers,
        json={"title": "Multi-turn chat"},
    )
    conv_id = create_resp.json()["id"]

    resp1 = await client.post(
        "/api/conversations/chat",
        headers=auth_headers,
        json={"message": "First message", "conversation_id": conv_id},
    )
    assert resp1.status_code == 200

    resp2 = await client.post(
        "/api/conversations/chat",
        headers=auth_headers,
        json={"message": "Second message", "conversation_id": conv_id},
    )
    assert resp2.status_code == 200
    assert resp2.json()["conversation_id"] == conv_id

    conv_resp = await client.get(
        f"/api/conversations/{conv_id}",
        headers=auth_headers,
    )
    messages = conv_resp.json().get("messages", [])
    assert len(messages) >= 4


@pytest.mark.asyncio
async def test_import_conversation(client: AsyncClient, auth_headers):
    """Import endpoint stores a conversation with its message history verbatim."""
    response = await client.post(
        "/api/conversations/import",
        headers=auth_headers,
        json={
            "title": "Imported Chat",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Imported Chat"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["content"] == "Hi there!"


# ── Guest Mode ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guest_can_chat(client: AsyncClient):
    """Guests can send a chat message without authentication."""
    response = await client.post(
        "/api/conversations/chat",
        json={"message": "Hello as guest"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["message"]["role"] == "assistant"


@pytest.mark.asyncio
async def test_guest_cannot_create_conversation(client: AsyncClient):
    """Guests cannot create server-persisted conversations."""
    response = await client.post(
        "/api/conversations/",
        json={"title": "Guest attempt"},
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_guest_list_conversations_empty(client: AsyncClient):
    """Guests see an empty conversation list (no server data)."""
    response = await client.get("/api/conversations/")
    assert response.status_code == 200
    assert response.json() == []
