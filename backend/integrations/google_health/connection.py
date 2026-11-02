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
from domains.body.models.body_metrics import BodyMetric
from domains.health_records.models.device_records import DailyHealthSummary, DeviceWorkout, HealthSample, SleepSession
from integrations.google_health.models import HealthConnection, HealthSyncRun
from domains.identity.models.oauth_account import OAuthAccount
from domains.identity.models.user import User
from domains.health_records.schemas.health import HEALTH_PROVIDER
from integrations.google_health.schemas import HealthConnectionRead, HealthSyncRunRead
from domains.identity import consent
from domains.shared.events import publish
from domains.shared.services.common import UserService
from integrations.google_health import oauth
from integrations.google_health.client import GoogleHealthError

logger = logging.getLogger(__name__)
DEVICE_TABLES = (("daily_days", DailyHealthSummary), ("sleep_sessions", SleepSession),
                 ("device_workouts", DeviceWorkout), ("health_samples", HealthSample))


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
            return HealthConnectionRead(configured=configured, connected=False)
        records = {}
        for name, model in DEVICE_TABLES:
            records[name] = (await self.session.execute(select(func.count()).select_from(model).where(
                model.user_id == self.user_id, model.is_active.is_(True)))).scalar_one()
        records["body_metrics"] = (await self.session.execute(select(func.count()).select_from(BodyMetric).where(
            BodyMetric.user_id == self.user_id, BodyMetric.is_active.is_(True),
            BodyMetric.source == HEALTH_PROVIDER))).scalar_one()
        run = (await self.session.execute(select(HealthSyncRun).where(HealthSyncRun.connection_id == connection.id)
                                          .order_by(HealthSyncRun.created_at.desc()).limit(1))).scalar_one_or_none()
        granted = list(connection.granted_scopes or [])
        decision = await consent.load(self.session, self.user_id)
        return HealthConnectionRead(
            configured=configured, connected=connection.status in {"ACTIVE", "NEEDS_REAUTH"},
            status=connection.status, account_email=connection.account_email, granted_scopes=granted,
            missing_scopes=oauth.missing_scopes(granted), share_with_assistant=decision.device,
            share_sensitive_with_assistant=decision.sensitive,
            consented_at=connection.consented_at if decision.device else None, timezone=connection.timezone,
            provider_profile=connection.provider_profile or {}, last_sync_at=connection.last_sync_at,
            last_success_at=connection.last_success_at, next_sync_at=connection.next_sync_at,
            last_error_code=connection.last_error_code, records=records,
            last_run=HealthSyncRunRead.model_validate(run) if run else None,
        )

    def start(self, share_with_assistant: bool | None, scopes: list[str] | None = None,
              then: str | None = None) -> tuple[str, str, str]:
        """URL đồng ý cùng nonce và PKCE verifier mà router lưu trong cookie HttpOnly."""
        require_configured()
        nonce = generate_secure_token(24)
        verifier, challenge = pkce_pair()
        state = oauth.create_state(self.user_id, nonce, share_with_assistant, then)
        return oauth.authorization_url(state=state, code_challenge=challenge, login_hint=self.user.email,
                                       scopes=scopes), nonce, verifier

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

    async def request_sync(self) -> UUID:
        connection = await self.connection()
        if connection is None or connection.status != "ACTIVE":
            raise HTTPException(409, "Kết nối Google Health không ở trạng thái hoạt động; hãy kết nối lại.")
        if connection.lease_until and connection.lease_until > datetime.now(timezone.utc):
            raise HTTPException(409, "Đang đồng bộ, vui lòng chờ trong giây lát.")
        return connection.id

    async def disconnect(self, purge_data: bool) -> HealthConnectionRead:
        connection = await HealthConnection.for_user(self.session, self.user_id, for_update=True)
        if connection is not None:
            await revoke_connection(connection)
            connection.status = "REVOKED"
            connection.access_token_enc = connection.refresh_token_enc = None
            connection.token_expires_at = connection.next_sync_at = None
            connection.lease_token = connection.lease_until = None
            # Lần sync hay job bắt đầu trước thời điểm này bị thế hệ mới fence lại.
            connection.generation += 1
            await self.session.flush()
            from core.jobs.queue import cancel_for_connection
            await cancel_for_connection(self.session, connection.id, "disconnected")
            await publish(self.session, "health.connection.changed", self.user_id,
                          {"status": "REVOKED", "generation": connection.generation})
        if purge_data:
            await purge_device_data(self.session, self.user_id)
        return await self.status()


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
    counts = {}
    for name, model in DEVICE_TABLES:
        counts[name] = (await session.execute(text(f"DELETE FROM {model.__tablename__} WHERE user_id = :uid"),
                                              {"uid": user_id})).rowcount or 0
    counts["body_metrics"] = (await session.execute(text(
        "DELETE FROM body_metrics WHERE user_id = :uid AND source = :source"),
        {"uid": user_id, "source": HEALTH_PROVIDER})).rowcount or 0
    # Delete imported records before their source layer; preserve manually written logs.
    for table in ("hydration_logs", "nutrition_logs", "ecg_recordings", "irn_alerts"):
        counts[table] = (await session.execute(text(f"DELETE FROM {table} WHERE user_id = :u AND source = :s"),
                            {"u": user_id, "s": HEALTH_PROVIDER})).rowcount or 0
    for table in ("health_source_records", "health_series_chunks", "paired_devices", "health_coverage",
                  "health_baselines", "derived_metrics", "context_snapshots"):
        counts[table] = (await session.execute(text(f"DELETE FROM {table} WHERE user_id = :u"),
                                               {"u": user_id})).rowcount or 0
    for table in ("sync_cursors", "shadow_diffs", "health_sync_runs"):
        await session.execute(text(f"DELETE FROM {table} WHERE connection_id IN "
            "(SELECT id FROM health_connections WHERE user_id = :u)"), {"u": user_id})
    await session.execute(text("DELETE FROM webhook_inbox WHERE health_user_id IN "
        "(SELECT health_user_id FROM health_connections WHERE user_id = :u)"), {"u": user_id})
    await session.execute(text("UPDATE health_connections SET provider_profile = '{}'::jsonb, "
        "sync_cursor = '{}'::jsonb, last_sync_at = NULL, last_success_at = NULL WHERE user_id = :u"), {"u": user_id})
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
    connection.next_sync_at = now
    if connection.id is not None:
        connection.generation += 1
    await session.flush()
    await consent.set_device(session, user.id, share)
    await publish(session, "health.connection.changed", user.id,
                  {"status": "ACTIVE", "generation": connection.generation})
    if claims.get("then") == "export_all":
        # Công tắc đồng bộ đã xin các scope này: bật nốt với những gì đã được cấp.
        from integrations.google_health.export import switch
        await switch.enable_all(session, connection, user.id)
    return "connected", connection.id


def _seconds(value: Any) -> timedelta:
    try:
        return timedelta(seconds=max(60, int(value)))
    except (TypeError, ValueError):
        return timedelta(hours=1)
