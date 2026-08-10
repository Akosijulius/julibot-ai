"""
Authentication endpoints for user registration and login.
"""

import secrets
from time import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_auth
from app.core.config import get_settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.database import get_db
from app.models.user import User
from app.schemas import Token, UserCreate, UserLogin, UserProfileUpdate, UserResponse
from app.schemas.user import GoogleLoginRequest

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_jwks_cache: dict = {}
_jwks_cache_time: float = 0.0
_JWKS_TTL_SECONDS = 3600  # Refresh Google's keys hourly


async def _get_google_jwks() -> dict:
    """Fetch and cache Google's JWKS keys (refreshed hourly)."""
    global _jwks_cache, _jwks_cache_time
    now = time()
    if not _jwks_cache or (now - _jwks_cache_time) > _JWKS_TTL_SECONDS:
        async with httpx.AsyncClient() as client:
            resp = await client.get(GOOGLE_JWKS_URL, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        _jwks_cache = {key["kid"]: key for key in data.get("keys", [])}
        _jwks_cache_time = now
    return _jwks_cache


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    """
    Register a new user account.

    Validates that password and confirm_password match before creating the user.
    """
    # Validate password confirmation
    if user_data.password != user_data.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match",
        )

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    # Create new user
    hashed_password = get_password_hash(user_data.password)
    user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=hashed_password,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.post("/login", response_model=Token)
async def login(user_data: UserLogin, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Authenticate a user and return a JWT token.

    The `login` field accepts either the user's email OR their username.
    """
    # Find user by email OR username
    result = await db.execute(
        select(User).where(
            (User.email == user_data.login) | (User.username == user_data.login)
        )
    )
    user = result.scalar_one_or_none()

    # Verify user exists and password is correct
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email, username, or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    # Create access token
    access_token = create_access_token(data={"sub": user.id})

    user_resp = UserResponse.model_validate(user)
    return {"access_token": access_token, "token_type": "bearer", "user": user_resp}


@router.post("/google", response_model=Token)
async def google_login(body: GoogleLoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Sign in with a Google ID token.

    Validates the token against Google's JWKS endpoint, then either logs in
    an existing user or creates a new one.
    """
    try:
        import base64

        from jose import jwt as jose_jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        jwks = await _get_google_jwks()

        # Find the key that signed the token
        header = jose_jwt.get_unverified_header(body.id_token)
        kid = header.get("kid")

        google_key = jwks.get(kid)
        if google_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google token: unknown key",
            )

        # Google JWK's n/e values are base64url-encoded unsigned integers
        def b64url_to_int(value: str) -> int:
            padding = "=" * (-len(value) % 4)
            return int.from_bytes(base64.urlsafe_b64decode(value + padding), "big")

        # Build the RSA public key from the JWK's n/e values.
        # Note: RSAPublicNumbers signature is (e, n).
        public_numbers = rsa.RSAPublicNumbers(
            b64url_to_int(google_key["e"]),
            b64url_to_int(google_key["n"]),
        )
        pem = public_numbers.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # Verify signature + expiry against our configured client ID
        payload = jose_jwt.decode(
            body.id_token,
            pem,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            options={"verify_exp": True},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Google token: {str(e)}",
        )

    # Extract user info from the token
    google_id: str = payload.get("sub", "")
    email: str = payload.get("email", "")
    name: str = payload.get("name", "")

    if not google_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google token missing required claims",
        )

    # Find existing user by email
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        # Create new user from Google info
        username = name.replace(" ", "").lower()[:50] or email.split("@")[0]
        # Ensure username is unique
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            username = f"{username}{secrets.token_hex(3)}"

        user = User(
            email=email,
            username=username,
            # OAuth users can't log in with a password, so store a random one
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            user_type="google",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Create access token
    access_token = create_access_token(data={"sub": user.id})
    user_resp = UserResponse.model_validate(user)

    return {"access_token": access_token, "token_type": "bearer", "user": user_resp}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(require_auth)) -> User:
    """
    Get current authenticated user information.
    """
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_current_user_info(
    update_data: UserProfileUpdate,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Update the authenticated user's profile (display name and/or profile photo).

    Only authenticated users can reach this (guests have no account to edit).
    """
    if "display_name" in update_data.model_fields_set:
        current_user.display_name = update_data.display_name
    if "profile_photo_url" in update_data.model_fields_set:
        # Explicit null clears the photo
        current_user.profile_photo_url = update_data.profile_photo_url

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user
