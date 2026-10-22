"""Authentication service implementing Google OAuth 2.0 and session management."""

from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import (
    REFRESH_TOKEN_COOKIE_NAME,
    STATE_COOKIE_NAME,
    create_access_token,
    generate_secure_token,
    hash_token,
)
from core.settings import settings
from models.auth_session import AuthSession
from models.basemodel import utc_now
from models.oauth_account import OAuthAccount
from models.user import User
from schemas.auth_session import AuthSessionCreate, LogoutResponse
from schemas.user import UserRead


class AuthService:
    """Handles Google OAuth callbacks, refresh token rotation, and session logout."""

    REDIRECT_URI_COOKIE_NAME = "oauth_redirect_uri"

    def __init__(self, session: AsyncSession, response: Response | None = None) -> None:
        self.session = session
        self.response = response

    def build_google_auth_url(self, state: str, redirect_uri: str | None = None) -> str:
        """Construct the Google OAuth 2.0 authorization consent URL."""
        target_redirect_uri = redirect_uri or settings.resolve_oauth_redirect_uri()
        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID or "",
            "redirect_uri": target_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    async def _exchange_google_code(
        self,
        code: str,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        """Exchange authorization code with Google token endpoint."""
        token_endpoint = "https://oauth2.googleapis.com/token"
        target_redirect_uri = redirect_uri or settings.resolve_oauth_redirect_uri()
        payload = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.google_client_secret_value,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": target_redirect_uri,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(token_endpoint, data=payload, timeout=15.0)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Google token exchange failed: {resp.text}",
                )
            return resp.json()

    async def _fetch_google_user_info(self, access_token: str) -> dict[str, Any]:
        """Fetch user profile information from Google userinfo API."""
        userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(userinfo_endpoint, headers=headers, timeout=15.0)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to fetch userinfo from Google: {resp.text}",
                )
            return resp.json()

    def _set_refresh_cookie(self, response: Response, raw_token: str) -> None:
        """Attach HTTP-only refresh token cookie to outgoing response."""
        response.set_cookie(
            key=REFRESH_TOKEN_COOKIE_NAME,
            value=raw_token,
            httponly=True,
            secure=not settings.is_dev(),
            samesite="lax",
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
            path="/",
        )

    async def handle_google_callback(
        self,
        code: str,
        state: str,
        oauth_state: str | None,
        *,
        redirect_uri: str | None = None,
        redirect_to_frontend: bool = False,
    ) -> Response:
        """Verify CSRF state, exchange code, upsert user and issue HercFit session tokens."""
        if not state or not oauth_state or state != oauth_state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or missing OAuth state parameter (CSRF verification failed)",
            )

        if redirect_uri:
            token_data = await self._exchange_google_code(code, redirect_uri=redirect_uri)
        else:
            token_data = await self._exchange_google_code(code)
        google_access_token = token_data.get("access_token", "")
        google_refresh_token = token_data.get("refresh_token")
        google_expires_in = token_data.get("expires_in")

        userinfo = await self._fetch_google_user_info(google_access_token)
        provider_user_id = str(userinfo.get("sub"))

        # 1. Upsert User in database
        user = await User.upsert_from_google(self.session, userinfo)
        if not user.is_active:
            raise HTTPException(401, "User account is inactive")

        # 2. Upsert OAuthAccount in database
        await OAuthAccount.upsert_google_account(
            self.session,
            user_id=user.id,
            provider_user_id=provider_user_id,
            token_data={
                "access_token": google_access_token,
                "refresh_token": google_refresh_token,
                "expires_in": google_expires_in,
            },
        )

        # 3. Create HercFit AuthSession & issue refresh token
        raw_refresh_token = generate_secure_token(64)
        refresh_token_hash = hash_token(raw_refresh_token)
        session_expires_at = utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        await AuthSession.create_session(
            self.session,
            AuthSessionCreate(
                user_id=user.id,
                refresh_token_hash=refresh_token_hash,
                expires_at=session_expires_at,
            ),
        )

        # 4. Generate JWT Access Token
        access_token = create_access_token(
            {
                "sub": str(user.id),
                "email": user.email,
                "fullname": user.fullname,
            }
        )

        user_read = UserRead.model_validate(user)
        if redirect_to_frontend:
            response: Response = RedirectResponse(
                url=f"{settings.FRONTEND_URL.rstrip('/')}/chat",
                status_code=status.HTTP_302_FOUND,
            )
        else:
            response = JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "access_token": access_token,
                    "token_type": "bearer",
                    "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                    "user": user_read.model_dump(mode="json"),
                },
            )

        self._set_refresh_cookie(response, raw_refresh_token)
        response.delete_cookie(key=STATE_COOKIE_NAME, path="/")
        response.delete_cookie(key=self.REDIRECT_URI_COOKIE_NAME, path="/")
        return response

    async def refresh_with_cookie(
        self,
        refresh_token: str | None,
        *,
        redirect_uri: str | None = None,
    ) -> Response:
        """Start OAuth flow if refresh_token is missing, or rotate session if valid."""
        # Case A: No refresh token -> Initiate Google OAuth flow
        if not refresh_token:
            state = generate_secure_token(32)
            auth_url = self.build_google_auth_url(state, redirect_uri=redirect_uri)
            redirect_resp = RedirectResponse(
                url=auth_url,
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            )
            redirect_resp.set_cookie(
                key=STATE_COOKIE_NAME,
                value=state,
                httponly=True,
                secure=not settings.is_dev(),
                samesite="lax",
                max_age=300,
                path="/",
            )
            if redirect_uri:
                redirect_resp.set_cookie(
                    key=self.REDIRECT_URI_COOKIE_NAME,
                    value=redirect_uri,
                    httponly=True,
                    secure=not settings.is_dev(),
                    samesite="lax",
                    max_age=300,
                    path="/",
                )
            return redirect_resp

        # Case B: Refresh token provided -> Validate & rotate
        refresh_token_hash = hash_token(refresh_token)
        auth_session = await AuthSession.get_by_refresh_token_hash(
            self.session,
            refresh_token_hash,
        )

        if auth_session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Token reuse detection: if already replaced or revoked, revoke subsequent chain
        if auth_session.revoked_at is not None or auth_session.replaced_by_session_id is not None:
            if auth_session.replaced_by_session_id:
                await AuthSession.revoke_replacement_chain(
                    self.session,
                    auth_session.replaced_by_session_id,
                )
                # This security revocation must survive the expected 401 response.
                await self.session.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has been revoked or reused",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not auth_session.is_refresh_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token is expired",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = await User.get_by_id(self.session, auth_session.user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive or not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Rotate refresh token
        new_raw_refresh_token = generate_secure_token(64)
        new_hash = hash_token(new_raw_refresh_token)
        new_expires_at = utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        new_session = await AuthSession.create_session(
            self.session,
            AuthSessionCreate(
                user_id=user.id,
                refresh_token_hash=new_hash,
                expires_at=new_expires_at,
            ),
        )
        await auth_session.revoke(self.session, replaced_by_session_id=new_session.id)

        access_token = create_access_token(
            {
                "sub": str(user.id),
                "email": user.email,
                "fullname": user.fullname,
            }
        )

        user_read = UserRead.model_validate(user)
        response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                "user": user_read.model_dump(mode="json"),
            },
        )
        self._set_refresh_cookie(response, new_raw_refresh_token)
        return response

    async def logout(self, refresh_token: str | None) -> LogoutResponse:
        """Revoke current refresh session and clear refresh token cookie."""
        if refresh_token:
            refresh_token_hash = hash_token(refresh_token)
            auth_session = await AuthSession.get_by_refresh_token_hash(
                self.session,
                refresh_token_hash,
            )
            if auth_session is not None and auth_session.revoked_at is None:
                await auth_session.revoke(self.session)

        if self.response is not None:
            self.response.delete_cookie(
                key=REFRESH_TOKEN_COOKIE_NAME,
                path="/",
            )
            self.response.delete_cookie(
                key=STATE_COOKIE_NAME,
                path="/",
            )

        return LogoutResponse(message="Logged out successfully")


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> AuthService:
    """FastAPI dependency yielding configured AuthService."""
    return AuthService(session=session, response=response)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

