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
DELEGATED_TOKEN_TYPE = "delegated"
AGENT_ACTOR = "hercfit-agentic"

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


def create_delegated_token(user_id: UUID, *, consent_version: int) -> tuple[str, datetime]:
    """A short-lived token for the agent service acting for `user_id` (RFC 8693 style `act`).

    Its audience differs from user tokens, so it can never be used as a user
    session, and the backend recognizes the agent from the token, not a header.
    """
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.AGENT_DELEGATION_MINUTES)
    claims = {"sub": str(user_id), "act": {"sub": AGENT_ACTOR}, "consent_version": int(consent_version),
              "iat": int(now.timestamp()), "nbf": int(now.timestamp()), "exp": int(expires.timestamp()),
              "iss": settings.JWT_ISSUER, "aud": settings.AGENT_TOKEN_AUDIENCE, "jti": uuid4().hex,
              "token_type": DELEGATED_TOKEN_TYPE}
    return jwt.encode(claims, settings.jwt_secret_value, algorithm="HS256"), expires


def _decode(token: str, audience: str, token_type: str) -> dict[str, Any] | None:
    """Claims when the token is valid for this audience and type; None for another audience."""
    for secret in settings.jwt_verification_secrets:
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                audience=audience,
                issuer=settings.JWT_ISSUER,
                leeway=settings.JWT_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.InvalidSignatureError:
            continue  # Signed with another (possibly retired) key.
        except jwt.InvalidAudienceError:
            return None
        except jwt.ExpiredSignatureError:
            # Raised only after the signature verified with this secret.
            raise _unauthorized("Token has expired") from None
        except jwt.PyJWTError:
            raise _unauthorized("Could not validate credentials") from None
        if payload.get("token_type") != token_type:
            raise _unauthorized("Invalid token type")
        return payload
    raise _unauthorized("Invalid token signature")


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature (current or retired secret), expiry, issuer, audience and type."""
    if settings.JWT_ALGORITHM != "HS256":
        raise _unauthorized("Invalid token algorithm")
    payload = _decode(token, settings.JWT_AUDIENCE, ACCESS_TOKEN_TYPE)
    if payload is None:
        raise _unauthorized("Could not validate credentials")
    return payload


def decode_bearer(token: str) -> tuple[dict[str, Any], bool]:
    """(claims, delegated): a user access token or a backend-issued delegated token."""
    if settings.JWT_ALGORITHM != "HS256":
        raise _unauthorized("Invalid token algorithm")
    payload = _decode(token, settings.JWT_AUDIENCE, ACCESS_TOKEN_TYPE)
    if payload is not None:
        return payload, False
    payload = _decode(token, settings.AGENT_TOKEN_AUDIENCE, DELEGATED_TOKEN_TYPE)
    if payload is None or (payload.get("act") or {}).get("sub") != AGENT_ACTOR:
        raise _unauthorized("Could not validate credentials")
    return payload, True


async def get_current_user(
    request: Request,
    http_auth: BearerCredentials,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """FastAPI dependency to retrieve the authenticated User model and set the principal."""
    from core import principal as principals
    from domains.identity.models.user import User

    payload, delegated = decode_bearer(http_auth.credentials)
    self_declared = request.headers.get(principals.AGENT_CLIENT_HEADER, "").lower() == "agent"
    if self_declared and not delegated and settings.AGENT_DELEGATION_REQUIRED:
        raise _unauthorized("The assistant must use a delegated token")
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
    kind = principals.PrincipalKind.AGENT if delegated or self_declared else principals.PrincipalKind.USER
    principals.set_current(principals.Principal(
        kind=kind, user_id=user.id, delegated=delegated,
        consent_version=payload.get("consent_version") if delegated else None))
    request.state.principal = principals.current()
    from agentic.observability import identify
    identify(str(user.id), private_values=(user.fullname, str(user.email), user.nick_name))
    return user
