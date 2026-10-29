"""Authentication service implementing Google OAuth 2.0 (PKCE) and session management."""

import hmac
import logging
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import (
    PKCE_COOKIE_NAME,
    REFRESH_TOKEN_COOKIE_NAME,
    STATE_COOKIE_NAME,
    create_access_token,
    generate_secure_token,
    hash_token,
    pkce_pair,
)
from core.settings import settings
from models.auth_session import AuthSession
from models.basemodel import utc_now
from models.oauth_account import OAuthAccount
from models.user import User
from schemas.auth_session import AuthSessionCreate, LogoutResponse
from schemas.user import UserRead

logger = logging.getLogger(__name__)
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
OAUTH_COOKIE_SECONDS = 300


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


class AuthService:
    """Handles Google OAuth callbacks, refresh token rotation, and session logout."""

    REDIRECT_URI_COOKIE_NAME = "oauth_redirect_uri"

    def __init__(self, session: AsyncSession, response: Response | None = None) -> None:
        self.session = session
        self.response = response

    # ------------------------------------------------------------------ OAuth
    def build_google_auth_url(self, state: str, redirect_uri: str | None = None,
                              code_challenge: str | None = None) -> str:
        """Identity-only consent URL: no offline access, Google tokens are never stored."""
        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID or "",
            "redirect_uri": redirect_uri or settings.resolve_oauth_redirect_uri(),
            "response_type": "code",
            "scope": "openid email profile",
            "prompt": "select_account",
            "state": state,
        }
        if code_challenge:
            params.update(code_challenge=code_challenge, code_challenge_method="S256")
        return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"

    async def _exchange_google_code(self, code: str, redirect_uri: str | None = None,
                                    code_verifier: str | None = None) -> dict[str, Any]:
        payload = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.google_client_secret_value,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri or settings.resolve_oauth_redirect_uri(),
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier
        async with httpx.AsyncClient() as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=payload, timeout=15.0)
        if resp.status_code != 200:
            # Provider bodies can echo request details; keep them out of client responses.
            logger.warning("google_token_exchange_failed status=%s", resp.status_code)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google không chấp nhận mã đăng nhập. Vui lòng đăng nhập lại.")
        return resp.json()

    async def _fetch_google_user_info(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=15.0)
        if resp.status_code != 200:
            logger.warning("google_userinfo_failed status=%s", resp.status_code)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Không đọc được thông tin tài khoản Google. Vui lòng thử lại.")
        return resp.json()

    def _set_cookie(self, response: Response, key: str, value: str, max_age: int) -> None:
        response.set_cookie(key=key, value=value, httponly=True, secure=settings.cookie_secure,
                            samesite="lax", max_age=max_age, path="/")

    def _set_refresh_cookie(self, response: Response, raw_token: str) -> None:
        self._set_cookie(response, REFRESH_TOKEN_COOKIE_NAME, raw_token, settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)

    def start_google_login(self, redirect_uri: str | None = None) -> Response:
        """Redirect to Google with CSRF state and a PKCE challenge kept in short-lived cookies."""
        state = generate_secure_token(32)
        verifier, challenge = pkce_pair()
        response = RedirectResponse(
            url=self.build_google_auth_url(state, redirect_uri=redirect_uri, code_challenge=challenge),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
        self._set_cookie(response, STATE_COOKIE_NAME, state, OAUTH_COOKIE_SECONDS)
        self._set_cookie(response, PKCE_COOKIE_NAME, verifier, OAUTH_COOKIE_SECONDS)
        if redirect_uri:
            self._set_cookie(response, self.REDIRECT_URI_COOKIE_NAME, redirect_uri, OAUTH_COOKIE_SECONDS)
        return response

    async def handle_google_callback(
        self,
        code: str,
        state: str,
        oauth_state: str | None,
        *,
        redirect_uri: str | None = None,
        redirect_to_frontend: bool = False,
        code_verifier: str | None = None,
    ) -> Response:
        """Verify CSRF state, exchange code (with PKCE), upsert user and issue HercFit tokens."""
        if not state or not oauth_state or not hmac.compare_digest(state, oauth_state):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Invalid or missing OAuth state parameter (CSRF verification failed)")

        token_data = await self._exchange_google_code(code, redirect_uri=redirect_uri, code_verifier=code_verifier)
        userinfo = await self._fetch_google_user_info(token_data.get("access_token", ""))
        provider_user_id = str(userinfo.get("sub"))

        user = await User.upsert_from_google(self.session, userinfo)
        if not user.is_active:
            raise _unauthorized("User account is inactive")
        # Only the provider identity is linked; Google access/refresh tokens are discarded.
        await OAuthAccount.upsert_google_account(self.session, user_id=user.id, provider_user_id=provider_user_id)

        raw_refresh_token = await self._create_refresh_session(user.id)
        access_token = self._access_token(user)
        if redirect_to_frontend:
            response: Response = RedirectResponse(url=f"{settings.FRONTEND_URL.rstrip('/')}/chat",
                                                  status_code=status.HTTP_302_FOUND)
        else:
            response = self._token_response(user, access_token)
        self._set_refresh_cookie(response, raw_refresh_token)
        for cookie in (STATE_COOKIE_NAME, PKCE_COOKIE_NAME, self.REDIRECT_URI_COOKIE_NAME):
            response.delete_cookie(key=cookie, path="/")
        return response

    # ---------------------------------------------------------------- Sessions
    async def _create_refresh_session(self, user_id) -> str:
        raw = generate_secure_token(64)
        await AuthSession.create_session(self.session, AuthSessionCreate(
            user_id=user_id, refresh_token_hash=hash_token(raw),
            expires_at=utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ))
        return raw

    @staticmethod
    def _access_token(user: User) -> str:
        return create_access_token({"sub": str(user.id), "email": user.email, "fullname": user.fullname})

    @staticmethod
    def _token_response(user: User, access_token: str) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": UserRead.model_validate(user).model_dump(mode="json"),
        })

    @staticmethod
    def _within_reuse_grace(previous: AuthSession, replacement: AuthSession | None) -> bool:
        """A concurrent refresh may present the token rotated a moment ago.

        Only the immediately preceding token qualifies, only for a short window,
        and only while its replacement is still the live head of the family.
        """
        grace = settings.REFRESH_REUSE_GRACE_SECONDS
        return bool(
            grace > 0 and previous.revoked_at is not None and replacement is not None
            and (utc_now() - previous.revoked_at).total_seconds() <= grace
            and replacement.revoked_at is None and replacement.replaced_by_session_id is None
            and replacement.is_refresh_valid
        )

    async def refresh(self, refresh_token: str | None) -> Response:
        """Rotate a valid refresh token; tolerate one concurrent reuse inside the grace window."""
        if not refresh_token:
            raise _unauthorized("Missing refresh token")
        auth_session = await AuthSession.get_by_refresh_token_hash(self.session, hash_token(refresh_token))
        if auth_session is None:
            raise _unauthorized("Invalid refresh token")

        if auth_session.replaced_by_session_id is not None:
            replacement = await AuthSession.get_for_update(self.session, auth_session.replaced_by_session_id)
            if self._within_reuse_grace(auth_session, replacement):
                user = await User.get_by_id(self.session, auth_session.user_id)
                if user is None or not user.is_active:
                    raise _unauthorized("User account is inactive or not found")
                # The browser already holds the replacement cookie from the winning
                # request; answering without Set-Cookie keeps that cookie intact.
                return self._token_response(user, self._access_token(user))
            # Reuse outside the window: treat as theft and revoke the whole family.
            await AuthSession.revoke_replacement_chain(self.session, auth_session.replaced_by_session_id)
            await self.session.commit()  # The revocation must survive the 401 response.
            raise _unauthorized("Refresh token has been revoked or reused")

        if auth_session.revoked_at is not None:
            raise _unauthorized("Refresh token has been revoked or reused")
        if not auth_session.is_refresh_valid:
            raise _unauthorized("Refresh token is expired")

        user = await User.get_by_id(self.session, auth_session.user_id)
        if user is None or not user.is_active:
            raise _unauthorized("User account is inactive or not found")

        new_raw = generate_secure_token(64)
        new_session = await AuthSession.create_session(self.session, AuthSessionCreate(
            user_id=user.id, refresh_token_hash=hash_token(new_raw),
            expires_at=utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ))
        await auth_session.revoke(self.session, replaced_by_session_id=new_session.id)
        response = self._token_response(user, self._access_token(user))
        self._set_refresh_cookie(response, new_raw)
        return response

    async def refresh_with_cookie(self, refresh_token: str | None, *, redirect_uri: str | None = None) -> Response:
        """Legacy GET contract: start OAuth when no cookie exists, otherwise rotate."""
        if not refresh_token:
            return self.start_google_login(redirect_uri)
        return await self.refresh(refresh_token)

    async def logout(self, refresh_token: str | None) -> LogoutResponse:
        """Revoke current refresh session and clear refresh token cookie."""
        if refresh_token:
            auth_session = await AuthSession.get_by_refresh_token_hash(self.session, hash_token(refresh_token))
            if auth_session is not None and auth_session.revoked_at is None:
                await auth_session.revoke(self.session)
        if self.response is not None:
            for cookie in (REFRESH_TOKEN_COOKIE_NAME, STATE_COOKIE_NAME, PKCE_COOKIE_NAME):
                self.response.delete_cookie(key=cookie, path="/")
        return LogoutResponse(message="Logged out successfully")


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> AuthService:
    """FastAPI dependency yielding configured AuthService."""
    return AuthService(session=session, response=response)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
