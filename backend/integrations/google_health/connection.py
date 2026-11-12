"""Kết nối, xem, đồng ý và ngắt kết nối tài khoản Google Health của người dùng."""
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select, text

from core.crypto import TokenCipherUnavailable, decrypt_secret, encrypt_secret
from core.security import generate_secure_token, pkce_pair
from core.settings import settings
from domains.health_records.models.health_points import HealthPoint
from domains.health_records.schemas.health import HEALTH_PROVIDER
from domains.health_records.types import SYNC_GROUPS
from domains.identity import consent
from domains.identity.models.oauth_account import OAuthAccount
from domains.identity.models.user import User
from domains.shared.services.common import UserService
from integrations.google_health import oauth
from integrations.google_health.client import GoogleHealthError
from integrations.google_health.models import HealthConnection
from integrations.google_health.schemas import HealthConnectionRead

logger = logging.getLogger(__name__)


def require_configured() -> None:
    if not settings.google_health_configured:
        raise HTTPException(503, "Kết nối Google Health chưa được cấu hình trên máy chủ.")


def frontend_result(result: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/chat?integration=google-health&result={result}"


class HealthConnectionService(UserService):
    async def connection(self) -> HealthConnection | None:
        return await HealthConnection.for_user(self.session, self.user_id)

    async def status(self) -> HealthConnectionRead:
        connection = await self.connection()
        configured = settings.google_health_configured
        if connection is None:
            return HealthConnectionRead(configured=configured, connected=False,
                                        sync_groups={group: True for group in SYNC_GROUPS})
        records = dict((await self.session.execute(
            select(HealthPoint.data_type, func.count()).where(HealthPoint.user_id == self.user_id)
            .group_by(HealthPoint.data_type))).all())
        granted = list(connection.granted_scopes or [])
        decision = await consent.load(self.session, self.user_id)
        return HealthConnectionRead(
            configured=configured, connected=connection.status in {"ACTIVE", "NEEDS_REAUTH"},
            status=connection.status, account_email=connection.account_email, granted_scopes=granted,
            missing_scopes=oauth.missing_scopes(granted), share_with_assistant=decision.device,
            share_sensitive_with_assistant=decision.sensitive,
            consented_at=connection.consented_at if decision.device else None, timezone=connection.timezone,
            provider_profile=connection.provider_profile or {}, last_sync_at=connection.last_sync_at,
            last_success_at=connection.last_success_at, last_error_code=connection.last_error_code,
            records=records, types=connection.sync_cursor or {},
            sync_groups=sync_groups(connection), sync_frequency=connection.sync_frequency or "hourly",
        )

    def start(self, share_with_assistant: bool | None) -> tuple[str, str, str]:
        """URL đồng ý cùng nonce và PKCE verifier mà router lưu trong cookie HttpOnly."""
        require_configured()
        nonce = generate_secure_token(24)
        verifier, challenge = pkce_pair()
        state = oauth.create_state(self.user_id, nonce, share_with_assistant)
        return oauth.authorization_url(state=state, code_challenge=challenge, login_hint=self.user.email), nonce, verifier

    async def update_consent(self, share_with_assistant: bool, *, sensitive: bool | None = None) -> HealthConnectionRead:
        from core import principal
        if principal.is_agent():
            raise HTTPException(403, "Chỉ người dùng được thay đổi quyền chia sẻ với trợ lý.")
        connection = await HealthConnection.for_user(self.session, self.user_id, for_update=True)
        if connection is None:
            raise HTTPException(404, "Chưa kết nối Google Health")
        # user_consents là quyết định; trigger của nó phát lại dữ liệu thiết bị lên graph.
        await consent.set_device(self.session, self.user_id, share_with_assistant)
        if sensitive is not None:
            await (consent.grant if sensitive else consent.revoke)(self.session, self.user_id, "sensitive")
        # Bản phản chiếu chỉ giữ để quay lui về code vẫn đọc cột này.
        if connection.share_with_assistant != share_with_assistant:
            connection.share_with_assistant = share_with_assistant
            connection.consented_at = datetime.now(timezone.utc) if share_with_assistant else None
        await self.session.flush()
        return await self.status()

    async def update_settings(self, groups: dict[str, bool] | None, frequency: str | None) -> HealthConnectionRead:
        """Nhóm dữ liệu được đồng bộ và tần suất. Tắt một nhóm chỉ dừng đọc nó; dữ liệu đã có giữ nguyên."""
        connection = await HealthConnection.for_user(self.session, self.user_id, for_update=True)
        if connection is None:
            raise HTTPException(404, "Chưa kết nối Google Health")
        if groups:
            connection.sync_groups = {**(connection.sync_groups or {}), **groups}
        if frequency:
            connection.sync_frequency = frequency
        await self.session.flush()
        return await self.status()

    async def require_active(self) -> HealthConnection:
        connection = await self.connection()
        if connection is None or connection.status != "ACTIVE":
            raise HTTPException(409, "Kết nối Google Health không ở trạng thái hoạt động; hãy kết nối lại.")
        return connection

    async def disconnect(self, purge_data: bool) -> HealthConnectionRead:
        connection = await HealthConnection.for_user(self.session, self.user_id, for_update=True)
        if connection is not None:
            await revoke_connection(connection)
            connection.status = "REVOKED"
            connection.access_token_enc = connection.refresh_token_enc = None
            connection.token_expires_at = None
            await self.session.flush()
        if purge_data:
            await purge_device_data(self.session, self.user_id)
        return await self.status()


def sync_groups(connection: HealthConnection) -> dict[str, bool]:
    stored = connection.sync_groups or {}
    return {group: stored.get(group) is not False for group in SYNC_GROUPS}


async def revoke_connection(connection: HealthConnection, http: httpx.AsyncClient | None = None) -> None:
    """Thu hồi quyền tại Google; lỗi không bao giờ chặn việc ngắt kết nối hay xoá dữ liệu."""
    token = connection.refresh_token_enc or connection.access_token_enc
    if not token:
        return
    try:
        secret = decrypt_secret(token)
    except TokenCipherUnavailable:
        logger.warning("google_health_revoke_skipped reason=credential_unavailable")
        return
    if http is not None:
        await oauth.revoke(http, secret)
        return
    async with httpx.AsyncClient() as client:
        await oauth.revoke(client, secret)


async def purge_device_data(session, user_id: UUID) -> dict[str, int]:
    """Xoá bản sao dữ liệu Google trong HercFit (dữ liệu trên Google giữ nguyên) và thu hồi consent.

    Chỉ xoá điểm đọc về từ thiết bị: số đo người dùng tự nhập qua HercFit (written_by_hercfit) được giữ lại."""
    counts = {
        "health_points": (await session.execute(
            text("DELETE FROM health_points WHERE user_id = :u AND written_by_hercfit = false"),
            {"u": user_id})).rowcount or 0,
        "google_pushes": (await session.execute(text("DELETE FROM google_pushes WHERE user_id = :u"),
                                                {"u": user_id})).rowcount or 0,
    }
    await session.execute(text("UPDATE health_connections SET provider_profile = '{}'::jsonb, "
                               "sync_cursor = '{}'::jsonb, last_sync_at = NULL, last_success_at = NULL "
                               "WHERE user_id = :u"), {"u": user_id})
    # Thu hồi consent đổi mọi dữ kiện thiết bị trong graph thành tombstone (kg_republish_health).
    await consent.set_device(session, user_id, False)
    await consent.revoke(session, user_id, "sensitive")
    return counts


async def complete_connect(session, *, code: str | None, state: str | None, error: str | None,
                           nonce_cookie: str | None, verifier: str | None,
                           http: httpx.AsyncClient | None = None) -> tuple[str, UUID | None]:
    """Xử lý chuyển hướng của Google. Trả về (kết quả cho frontend, id kết nối cần đồng bộ)."""
    if not settings.google_health_configured:
        return "error", None
    if error:
        return "denied", None
    try:
        claims = oauth.verify_state(state or "")
    except ValueError:
        return "error", None
    if not code or not verifier or not nonce_cookie or not hmac.compare_digest(str(claims["nonce"]), nonce_cookie):
        return "error", None
    user = await User.get_by_id(session, UUID(claims["sub"]))
    if user is None or not user.is_active:
        return "error", None
    if http is None:
        async with httpx.AsyncClient() as client:
            return await _link(session, user, claims, code, verifier, client)
    return await _link(session, user, claims, code, verifier, http)


async def _link(session, user: User, claims: dict[str, Any], code: str, verifier: str,
                http: httpx.AsyncClient) -> tuple[str, UUID | None]:
    try:
        tokens = await oauth.exchange_code(http, code, verifier)
        userinfo = await oauth.fetch_userinfo(http, tokens["access_token"])
    except GoogleHealthError:
        return "error", None
    login = await OAuthAccount.get_one(session, user_id=user.id, provider="google")
    subject = str(userinfo.get("sub") or "")
    if login is None or not hmac.compare_digest(subject, login.provider_user_id):
        # Dữ liệu sức khoẻ phải đến từ tài khoản Google mà người dùng đăng nhập.
        await oauth.revoke(http, tokens.get("refresh_token") or tokens.get("access_token"))
        return "wrong_account", None
    granted = oauth.granted_scopes(tokens)
    if not granted:
        await oauth.revoke(http, tokens.get("refresh_token") or tokens.get("access_token"))
        return "denied", None
    connection = await HealthConnection.for_user(session, user.id, for_update=True)
    if connection is None:
        connection = HealthConnection(user_id=user.id, provider=HEALTH_PROVIDER, provider_subject=subject)
        session.add(connection)
    if not tokens.get("refresh_token") and not connection.refresh_token_enc:
        return "error", None
    # None: một lần uỷ quyền tăng dần, giữ nguyên consent của trợ lý.
    share = claims.get("share")
    if share is None:
        share = (await consent.load(session, user.id)).device
    share = bool(share)
    now = datetime.now(timezone.utc)
    connection.provider_subject = subject
    connection.account_email = str(userinfo.get("email") or user.email)[:255]
    connection.granted_scopes = granted
    connection.access_token_enc = encrypt_secret(tokens["access_token"])
    if tokens.get("refresh_token"):
        connection.refresh_token_enc = encrypt_secret(tokens["refresh_token"])
    connection.token_expires_at = now + _seconds(tokens.get("expires_in"))
    connection.status = "ACTIVE"
    connection.is_active = True
    if share and not connection.share_with_assistant:
        connection.consented_at = now
    elif not share:
        connection.consented_at = None
    connection.share_with_assistant = share
    connection.last_error_code = None
    await session.flush()
    await consent.set_device(session, user.id, share)
    return "connected", connection.id


def _seconds(value: Any) -> timedelta:
    try:
        return timedelta(seconds=max(60, int(value)))
    except (TypeError, ValueError):
        return timedelta(hours=1)
