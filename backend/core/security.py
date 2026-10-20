"""Authentication and user context dependencies for FastAPI routers."""

import base64
import hashlib
import hmac
import json
import math
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.settings import settings

STATE_COOKIE_NAME = "oauth_state"
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"

bearer_scheme = HTTPBearer(description="Provide Bearer token or AUTH_SECRET.", auto_error=False)
strict_bearer_scheme = HTTPBearer(description="Provide Bearer JWT token.", auto_error=True)


def get_refresh_token_cookie(request: Request) -> str | None:
    """Extract refresh token from request cookies without raising 422 if missing."""
    return request.cookies.get(REFRESH_TOKEN_COOKIE_NAME)


BearerCredentials = Annotated[HTTPAuthorizationCredentials, Depends(strict_bearer_scheme)]
RefreshTokenCookie = Annotated[str | None, Depends(get_refresh_token_cookie)]


def hash_token(token: str) -> str:
    """Return SHA-256 hexadecimal digest of token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_secure_token(nbytes: int = 32) -> str:
    """Generate cryptographically strong URL-safe random string."""
    return secrets.token_urlsafe(nbytes)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("ascii"))


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a signed HS256 JWT access token."""
    if settings.JWT_ALGORITHM != "HS256":
        raise ValueError("Only HS256 is supported")
    claims = dict(data)
    now = datetime.now(timezone.utc)
    iat = int(now.timestamp())
    if expires_delta is not None:
        exp = int((now + expires_delta).timestamp())
    else:
        exp = int((now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp())

    claims.setdefault("iat", iat)
    claims["exp"] = exp

    secret = settings.jwt_secret_value.encode("utf-8")
    header = {"alg": settings.JWT_ALGORITHM, "typ": "JWT"}
    header_b64 = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64encode(json.dumps(claims, separators=(",", ":"), default=str).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = _b64encode(hmac.new(secret, signing_input, hashlib.sha256).digest())
    return f"{header_b64}.{payload_b64}.{signature}"


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a signed HS256 JWT access token."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format",
                headers={"WWW-Authenticate": "Bearer"},
            )
        header_b64, payload_b64, signature_b64 = parts
        header = json.loads(_b64decode(header_b64).decode("utf-8"))
        if header.get("alg") != "HS256" or settings.JWT_ALGORITHM != "HS256":
            raise HTTPException(401, "Invalid token algorithm", headers={"WWW-Authenticate": "Bearer"})
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        secret = settings.jwt_secret_value.encode("utf-8")
        expected_sig = _b64encode(hmac.new(secret, signing_input, hashlib.sha256).digest())
        if not hmac.compare_digest(signature_b64, expected_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token signature",
                headers={"WWW-Authenticate": "Bearer"},
            )
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        if isinstance(exp, bool) or not isinstance(exp, (int, float)) or not math.isfinite(exp):
            raise HTTPException(401, "Invalid token expiry", headers={"WWW-Authenticate": "Bearer"})
        if time.time() >= exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_bearer(
    http_auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    if not settings.AUTH_SECRET:
        return
    auth_secret = settings.AUTH_SECRET.get_secret_value()
    if not http_auth or http_auth.credentials != auth_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


async def get_current_user_id(
    http_auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str:
   

    if x_user_id:
        return x_user_id
    if settings.is_dev():
        return "default-user"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


async def get_current_user(
    http_auth: BearerCredentials,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """FastAPI dependency to retrieve the authenticated User model."""
    from models.user import User

    payload = decode_access_token(http_auth.credentials)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_uuid = UUID(user_id_str)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID format in token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await User.get_by_id(session, user_uuid)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
