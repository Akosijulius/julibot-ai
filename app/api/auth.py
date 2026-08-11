"""
Authentication endpoints for user registration and login.
"""

import secrets
from time import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_auth
from app.core.config import get_settings
from app.core.security import get_password_hash, verify_password
from app.db.database import get_db
from app.models.user import User
from app.schemas import Token, UserCreate, UserLogin, UserProfileUpdate, UserResponse
from app.schemas.user import GoogleLoginRequest
from app.services.account_service import delete_account
from app.services.auth_service import clear_access_cookie, issue_session, revoke_all_user_sessions, revoke_session, set_access_cookie

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
        # Generic message on purpose — distinct "email/username taken" errors
        # would let attackers enumerate which accounts already exist.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration failed. Please try again or log in.",
        )

    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration failed. Please try again or log in.",
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
async def login(
    user_data: UserLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Authenticate a user and return a JWT token.

    The `login` field accepts either the user's email OR their username.

    On success the token is set as an HttpOnly cookie (for the browser) AND
    returned in the body (for API clients). A server-side Session is created
    so the token can be revoked on logout.
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

    access_token, _session = await issue_session(db, user, request)
    set_access_cookie(response, access_token)

    user_resp = UserResponse.model_validate(user)
    return {"access_token": access_token, "token_type": "bearer", "user": user_resp}


@router.post("/google", response_model=Token)
async def google_login(
    body: GoogleLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Sign in with a Google ID token.

    Validates the token against Google's JWKS endpoint, then either logs in
    an existing user or creates a new one. Sets the access-token HttpOnly
    cookie on success.
    """
    try:
        import base64

        import jwt
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        jwks = await _get_google_jwks()

        # Find the key that signed the token
        header = jwt.get_unverified_header(body.id_token)
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

        # Verify signature + expiry + issuer + audience against Google's claims.
        # PyJWT validates `exp`, `iat`, `nbf`, `aud` and `iss` by default here.
        # `leeway` tolerates small clock skew: Google can issue a token whose
        # `iat` is a few seconds ahead of this server's clock, which otherwise
        # raises ImmatureSignatureError ("The token is not yet valid (iat)").
        # The skew window is bounded and small, so expiry is not meaningfully
        # weakened. Signature, audience, issuer and exp remain strictly checked.
        payload = jwt.decode(
            body.id_token,
            pem,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer="https://accounts.google.com",
            leeway=30,
        )

        # Only accept tokens with a verified email address.
        if str(payload.get("email_verified", "")).lower() != "true":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google account email is not verified",
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

    access_token, _session = await issue_session(db, user, request)
    set_access_cookie(response, access_token)

    user_resp = UserResponse.model_validate(user)
    return {"access_token": access_token, "token_type": "bearer", "user": user_resp}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Log out the current session: revoke the server-side session and clear the
    access-token cookie. After this, the current token is invalid.
    """
    jti = getattr(request.state, "jti", None)
    if jti:
        await revoke_session(db, jti)
    clear_access_cookie(response)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Log out every session for the current user (all devices). Clears the
    current cookie and revokes all server-side sessions.
    """
    await revoke_all_user_sessions(db, current_user.id)
    clear_access_cookie(response)


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


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_account(
    response: Response,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Permanently delete the authenticated user's account and all their data.

    Removes conversations, messages, sessions, and usage rows in one
    transaction, then clears the access-token cookie. After this the user
    cannot log back in and must re-register.
    """
    await delete_account(db, current_user)
    clear_access_cookie(response)
