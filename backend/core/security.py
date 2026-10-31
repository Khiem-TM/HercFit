"""Authentication and user context dependencies for FastAPI routers."""

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.settings import settings

STATE_COOKIE_NAME = "oauth_state"
PKCE_COOKIE_NAME = "oauth_pkce"
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"
ACCESS_TOKEN_TYPE = "access"

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


def pkce_pair() -> tuple[str, str]:
    """RFC 7636 S256 verifier/challenge pair for the OAuth authorization code flow."""
    verifier = secrets.token_urlsafe(64)  # 86 unreserved characters (43..128 allowed)
    challenge = _b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class _ClaimEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:  # UUIDs, datetimes and enums in caller claims
        return str(o)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a signed HS256 access token with issuer, audience and token type."""
    if settings.JWT_ALGORITHM != "HS256":
        raise ValueError("Only HS256 is supported")
    now = datetime.now(timezone.utc)
    lifetime = expires_delta if expires_delta is not None else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = dict(data)
    claims.update(
        iat=int(now.timestamp()),
        nbf=int(now.timestamp()),
        exp=int((now + lifetime).timestamp()),
        iss=settings.JWT_ISSUER,
        aud=settings.JWT_AUDIENCE,
        jti=uuid4().hex,
        token_type=ACCESS_TOKEN_TYPE,
    )
    return jwt.encode(claims, settings.jwt_secret_value, algorithm="HS256", json_encoder=_ClaimEncoder)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature (current or retired secret), expiry, issuer, audience and type."""
    if settings.JWT_ALGORITHM != "HS256":
        raise _unauthorized("Invalid token algorithm")
    for secret in settings.jwt_verification_secrets:
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience=settings.JWT_AUDIENCE,
                issuer=settings.JWT_ISSUER,
                leeway=settings.JWT_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.InvalidSignatureError:
            continue  # Signed with another (possibly retired) key.
        except jwt.ExpiredSignatureError:
            # Raised only after the signature verified with this secret.
            raise _unauthorized("Token has expired") from None
        except jwt.PyJWTError:
            raise _unauthorized("Could not validate credentials") from None
        if payload.get("token_type") != ACCESS_TOKEN_TYPE:
            raise _unauthorized("Invalid token type")
        return payload
    raise _unauthorized("Invalid token signature")


async def get_current_user(
    http_auth: BearerCredentials,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """FastAPI dependency to retrieve the authenticated User model."""
    from models.user import User

    payload = decode_access_token(http_auth.credentials)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise _unauthorized("Token subject missing")
    try:
        user_uuid = UUID(str(user_id_str))
    except (ValueError, TypeError, AttributeError):
        raise _unauthorized("Invalid user ID format in token") from None

    user = await User.get_by_id(session, user_uuid)
    if user is None or not user.is_active:
        raise _unauthorized("User account is inactive or not found")
    from agentic.observability import identify
    identify(str(user.id), private_values=(user.fullname, str(user.email), user.nick_name))
    return user
