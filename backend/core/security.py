"""Authentication and user context dependencies for FastAPI routers."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.settings import settings

bearer_scheme = HTTPBearer(description="Provide Bearer token or AUTH_SECRET.", auto_error=False)


def verify_bearer(
    http_auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    if not settings.AUTH_SECRET:
        return
    auth_secret = settings.AUTH_SECRET.get_secret_value()
    if not http_auth or http_auth.credentials != auth_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


async def get_current_user_id(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    _auth: Annotated[None, Depends(verify_bearer)] = None,
) -> str:
    """Resolve current user_id from request header or JWT token payload.

    TODO: Replace header fallback with JWT decoding using settings.JWT_SECRET.
    """
    return x_user_id or "default-user"
