"""
Tests for Stage 1 security hardening:

- HttpOnly-cookie auth and server-side session revocation (logout / logout-all)
- Conversation-import size bounds (schema-level)
- Per-user daily AI usage quota (429 enforcement)
"""

import pytest
from httpx import AsyncClient

from app.services.auth_service import ACCESS_COOKIE


@pytest.mark.asyncio
async def test_login_sets_http_only_cookie(client: AsyncClient, test_user):
    """Login sets an HttpOnly access-token cookie usable for auth."""
    resp = await client.post(
        "/api/auth/login",
        json={"login": test_user.email, "password": "testpassword123"},
    )
    assert resp.status_code == 200

    set_cookie = resp.headers.get("set-cookie", "")
    assert ACCESS_COOKIE in set_cookie
    assert "HttpOnly" in set_cookie

    # The cookie (stored by the client) now authenticates /auth/me.
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == test_user.email


@pytest.mark.asyncio
async def test_logout_revokes_session_and_clears_cookie(client: AsyncClient, test_user):
    """After logout the cookie is cleared and the session is revoked (401)."""
    await client.post(
        "/api/auth/login",
        json={"login": test_user.email, "password": "testpassword123"},
    )
    assert (await client.get("/api/auth/me")).status_code == 200

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 204

    # Cookie is cleared server-side; the client no longer holds a valid session.
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_logout_all_revokes_sessions(client: AsyncClient, test_user):
    """logout-all revokes every session and clears the current cookie."""
    await client.post(
        "/api/auth/login",
        json={"login": test_user.email, "password": "testpassword123"},
    )
    assert (await client.get("/api/auth/me")).status_code == 200

    resp = await client.post("/api/auth/logout-all")
    assert resp.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_import_rejects_too_many_messages(client: AsyncClient, auth_headers):
    """Importing more than the allowed message count is rejected (422)."""
    messages = [{"role": "user", "content": "hi"} for _ in range(201)]
    resp = await client.post(
        "/api/conversations/import",
        headers=auth_headers,
        json={"title": "Big import", "messages": messages},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_rejects_total_size_exceeding_limit(client: AsyncClient, auth_headers):
    """Import whose combined content size exceeds the cap is rejected (422)."""
    # 11 × 100k chars = 1.1M > the 1M total-content cap.
    messages = [{"role": "user", "content": "x" * 100_000} for _ in range(11)]
    resp = await client.post(
        "/api/conversations/import",
        headers=auth_headers,
        json={"title": "Oversized import", "messages": messages},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_quota_limits_daily_requests(client: AsyncClient, test_user, monkeypatch):
    """A registered user is blocked (429) once they hit their daily request quota."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "quota_enabled", True)
    monkeypatch.setattr(settings, "quota_daily_requests", 1)

    await client.post(
        "/api/auth/login",
        json={"login": test_user.email, "password": "testpassword123"},
    )

    first = await client.post("/api/conversations/chat", json={"message": "hello"})
    assert first.status_code == 200

    second = await client.post("/api/conversations/chat", json={"message": "hello again"})
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_guests_are_not_quota_limited(client: AsyncClient):
    """Guests have no persisted row and bypass the per-user quota (still IP rate limited)."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings, "quota_enabled", True)
    monkeypatch.setattr(settings, "quota_daily_requests", 0)

    try:
        for _ in range(3):
            resp = await client.post("/api/conversations/chat", json={"message": "hi guest"})
            assert resp.status_code == 200
    finally:
        monkeypatch.undo()
