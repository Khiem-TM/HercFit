"""OAuth 2.0 cho Google Health API: URL đồng ý, state có chữ ký và các lời gọi token.

Luồng kết nối tách khỏi đăng nhập. Đăng nhập chỉ lấy danh tính; luồng này
xin truy cập offline vào các scope sức khoẻ chỉ đọc, và callback chỉ chấp nhận
tài khoản Google mà người dùng đã đăng nhập.

Tham số state là JWT HS256 với audience và loại token riêng, nên nó
không bao giờ phát lại được như access token của HercFit. Nonce của nó cũng phải khớp một
cookie HttpOnly, gắn callback với trình duyệt đã bắt đầu luồng.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import jwt

from core.settings import settings
from domains.identity.services.auth_service import GOOGLE_AUTHORIZE_URL, GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL
from integrations.google_health.client import GoogleHealthError, ReauthRequired

logger = logging.getLogger(__name__)
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPE_PREFIX = "https://www.googleapis.com/auth/googlehealth."
# Luồng kết nối mặc định xin các scope đọc này; scope ghi chỉ được xin
# khi người dùng bật một nhóm xuất (các gói trong contract/scopes.py).
SCOPES = {
    "activity": SCOPE_PREFIX + "activity_and_fitness.readonly",
    "health_metrics": SCOPE_PREFIX + "health_metrics_and_measurements.readonly",
    "sleep": SCOPE_PREFIX + "sleep.readonly",
    "profile": SCOPE_PREFIX + "profile.readonly",
    "settings": SCOPE_PREFIX + "settings.readonly",
    "nutrition": SCOPE_PREFIX + "nutrition.readonly",
}
IDENTITY_SCOPES = ("openid", "email")
STATE_AUDIENCE = "hercfit-google-health-connect"
STATE_TOKEN_TYPE = "oauth_state"
STATE_SECONDS = 600
NONCE_COOKIE = "health_oauth_nonce"
PKCE_COOKIE = "health_oauth_pkce"
TIMEOUT = 15.0


def authorization_url(*, state: str, code_challenge: str, login_hint: str | None,
                      scopes: list[str] | None = None) -> str:
    """URL đồng ý. `scopes` xin thêm các gói tính năng (uỷ quyền tăng dần);
    include_granted_scopes giữ những gì người dùng đã cấp."""
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID or "",
        "redirect_uri": settings.google_health_redirect_uri,
        "response_type": "code",
        "scope": " ".join((*IDENTITY_SCOPES, *(scopes or SCOPES.values()))),
        "access_type": "offline",
        # Luôn hiển thị màn hình đồng ý để Google trả về refresh token và cho người dùng
        # xem lại từng scope sức khoẻ (đồng ý chi tiết).
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


def create_state(user_id: UUID, nonce: str, share_with_assistant: bool | None, then: str | None = None) -> str:
    """`share` là None (uỷ quyền tăng dần) thì giữ nguyên consent của trợ lý.
    `then` gọi tên việc callback làm nốt khi scope đã được cấp (export/switch.py)."""
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "nonce": nonce, "share": share_with_assistant,
              "iat": int(now.timestamp()), "exp": int((now + timedelta(seconds=STATE_SECONDS)).timestamp()),
              "iss": settings.JWT_ISSUER, "aud": STATE_AUDIENCE, "token_type": STATE_TOKEN_TYPE}
    if then:
        claims["then"] = then
    return jwt.encode(claims, settings.jwt_secret_value, algorithm="HS256")


def verify_state(token: str) -> dict[str, Any]:
    for secret in settings.jwt_verification_secrets:
        try:
            claims = jwt.decode(token, secret, algorithms=["HS256"], audience=STATE_AUDIENCE,
                                issuer=settings.JWT_ISSUER, leeway=settings.JWT_LEEWAY_SECONDS,
                                options={"require": ["exp", "iat", "sub", "aud", "iss"]})
        except jwt.InvalidSignatureError:
            continue
        except jwt.PyJWTError:
            raise ValueError("invalid_state") from None
        if claims.get("token_type") != STATE_TOKEN_TYPE or not claims.get("nonce"):
            raise ValueError("invalid_state")
        return claims
    raise ValueError("invalid_state")


def granted_scopes(token_data: dict[str, Any]) -> list[str]:
    return sorted(scope for scope in str(token_data.get("scope") or "").split() if scope.startswith(SCOPE_PREFIX))


def missing_scopes(granted: list[str]) -> list[str]:
    return sorted(set(SCOPES.values()) - set(granted))


async def _token_call(http: httpx.AsyncClient, data: dict[str, str]) -> dict[str, Any]:
    try:
        response = await http.post(GOOGLE_TOKEN_URL, data=data, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        logger.warning("google_health_token_network error=%s", type(exc).__name__)
        raise GoogleHealthError("network") from None
    if response.status_code == 200:
        return response.json()
    try:
        error = response.json().get("error")
    except ValueError:
        error = None
    logger.warning("google_health_token_failed status=%s error=%s", response.status_code, error)
    if error == "invalid_grant":
        raise ReauthRequired(response.status_code)
    raise GoogleHealthError("token_error", response.status_code)


async def exchange_code(http: httpx.AsyncClient, code: str, code_verifier: str) -> dict[str, Any]:
    return await _token_call(http, {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID or "", "client_secret": settings.google_client_secret_value,
        "code": code, "grant_type": "authorization_code", "redirect_uri": settings.google_health_redirect_uri,
        "code_verifier": code_verifier,
    })


async def refresh_access_token(http: httpx.AsyncClient, refresh_token: str) -> dict[str, Any]:
    return await _token_call(http, {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID or "", "client_secret": settings.google_client_secret_value,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    })


async def fetch_userinfo(http: httpx.AsyncClient, access_token: str) -> dict[str, Any]:
    try:
        response = await http.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"},
                                  timeout=TIMEOUT)
    except httpx.HTTPError:
        raise GoogleHealthError("network") from None
    if response.status_code != 200:
        logger.warning("google_health_userinfo_failed status=%s", response.status_code)
        raise GoogleHealthError("userinfo_error", response.status_code)
    return response.json()


async def revoke(http: httpx.AsyncClient, token: str | None) -> bool:
    """Cố gắng hết mức: token đã không còn hợp lệ thì không cần thu hồi."""
    if not token:
        return False
    try:
        response = await http.post(REVOKE_URL, data={"token": token}, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        logger.warning("google_health_revoke_network error=%s", type(exc).__name__)
        return False
    if response.status_code not in (200, 400):
        logger.warning("google_health_revoke_failed status=%s", response.status_code)
    return response.status_code == 200
