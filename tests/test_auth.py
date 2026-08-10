"""
Tests for user authentication endpoints.
"""

import pytest
from httpx import AsyncClient


def register_payload(**overrides):
    """Build a valid registration payload, optionally overriding fields."""
    payload = {
        "email": "newuser@example.com",
        "username": "newuser123",
        "password": "securepass123",
        "confirm_password": "securepass123",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_register_new_user(client: AsyncClient):
    """A new user can register successfully."""
    response = await client.post("/api/auth/register", json=register_payload())
    assert response.status_code == 201, f"Body: {response.text}"
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["username"] == "newuser123"
    assert "id" in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_register_password_mismatch(client: AsyncClient):
    """Registration rejects mismatched password confirmation."""
    response = await client.post(
        "/api/auth/register",
        json=register_payload(password="password123", confirm_password="different123"),
    )
    assert response.status_code == 400
    assert "match" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, test_user):
    """Registering with an existing email returns 400."""
    response = await client.post(
        "/api/auth/register",
        json=register_payload(
            email=test_user.email,
            username="another_user",
        ),
    )
    assert response.status_code == 400
    assert "email" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient, test_user):
    """Registering with an existing username returns 400."""
    response = await client.post(
        "/api/auth/register",
        json=register_payload(
            email="other@example.com",
            username=test_user.username,
        ),
    )
    assert response.status_code == 400
    assert "username" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient):
    """Registration rejects invalid email addresses."""
    response = await client.post(
        "/api/auth/register",
        json=register_payload(email="not-an-email"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient):
    """Registration rejects passwords shorter than 8 characters."""
    response = await client.post(
        "/api/auth/register",
        json=register_payload(password="short", confirm_password="short"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success_email(client: AsyncClient, test_user):
    """Login with correct email returns a token."""
    response = await client.post(
        "/api/auth/login",
        json={
            "login": test_user.email,
            "password": "testpassword123",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_success_username(client: AsyncClient, test_user):
    """Login with the username (instead of email) also works."""
    response = await client.post(
        "/api/auth/login",
        json={
            "login": test_user.username,
            "password": "testpassword123",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_user):
    """Login with wrong password returns 401."""
    response = await client.post(
        "/api/auth/login",
        json={
            "login": test_user.email,
            "password": "wrongpassword",
        },
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    """Login with nonexistent email returns 401."""
    response = await client.post(
        "/api/auth/login",
        json={
            "login": "nobody@example.com",
            "password": "somepassword",
        },
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_current_user(client: AsyncClient, auth_headers):
    """Authenticated user can retrieve their own profile."""
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "email" in data
    assert "username" in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_protected_route_without_token(client: AsyncClient):
    """Unauthenticated requests to /me return 401/403."""
    response = await client.get("/api/auth/me")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_me_includes_profile_fields(client: AsyncClient, auth_headers):
    """GET /me returns display_name and profile_photo_url fields."""
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "display_name" in data
    assert "profile_photo_url" in data
    assert data["display_name"] is None
    assert data["profile_photo_url"] is None


@pytest.mark.asyncio
async def test_update_display_name(client: AsyncClient, auth_headers):
    """PATCH /me updates the display name and returns it."""
    response = await client.patch(
        "/api/auth/me",
        json={"display_name": "Jane Smith"},
        headers=auth_headers,
    )
    assert response.status_code == 200, f"Body: {response.text}"
    data = response.json()
    assert data["display_name"] == "Jane Smith"

    # Persisted — a follow-up GET reflects the change
    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["display_name"] == "Jane Smith"


@pytest.mark.asyncio
async def test_update_profile_photo(client: AsyncClient, auth_headers):
    """PATCH /me accepts an image data URL for the profile photo."""
    photo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    response = await client.patch(
        "/api/auth/me",
        json={"profile_photo_url": photo},
        headers=auth_headers,
    )
    assert response.status_code == 200, f"Body: {response.text}"
    data = response.json()
    assert data["profile_photo_url"] == photo


@pytest.mark.asyncio
async def test_update_profile_invalid_photo(client: AsyncClient, auth_headers):
    """PATCH /me rejects non-image data URLs."""
    response = await client.patch(
        "/api/auth/me",
        json={"profile_photo_url": "https://example.com/photo.png"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_profile_clears_photo(client: AsyncClient, auth_headers):
    """PATCH /me with an explicit null clears the profile photo."""
    photo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    set_response = await client.patch(
        "/api/auth/me",
        json={"profile_photo_url": photo},
        headers=auth_headers,
    )
    assert set_response.status_code == 200

    clear_response = await client.patch(
        "/api/auth/me",
        json={"profile_photo_url": None},
        headers=auth_headers,
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["profile_photo_url"] is None


@pytest.mark.asyncio
async def test_update_profile_partial_keeps_photo(client: AsyncClient, auth_headers):
    """PATCH /me for display name alone does not wipe the profile photo."""
    photo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    await client.patch(
        "/api/auth/me",
        json={"profile_photo_url": photo},
        headers=auth_headers,
    )
    response = await client.patch(
        "/api/auth/me",
        json={"display_name": "Jane"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "Jane"
    assert data["profile_photo_url"] == photo


@pytest.mark.asyncio
async def test_update_profile_requires_auth(client: AsyncClient):
    """PATCH /me without a token is rejected."""
    response = await client.patch("/api/auth/me", json={"display_name": "X"})
    assert response.status_code in (401, 403)
