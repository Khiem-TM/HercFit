"""Service nghiệp vụ của miền danh tính và quyền riêng tư."""

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core import service_auth
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
from domains.body.models import BodyMetric
from domains.body.schemas import BodyMetricCreate, BodyMetricQuery, LatestBodyMetricField
from domains.goals_plans.models import Goal
from domains.goals_plans.schemas import GoalCreate, GoalUpdateRequest
from domains.identity.models import AuthSession, OAuthAccount, User
from domains.identity.schemas import (
    AuthSessionCreate,
    LogoutResponse,
    OnboardingInput,
    UserRead,
    UserUpdate,
)
from domains.shared.models import utc_now
from domains.shared.schemas import JsonObject, Pagination
from domains.shared.services import UserService, request_validation_error, require_found

# --------------------------------------------------------------------------------------------------
# Service xác thực cài đặt Google OAuth 2.0 (PKCE) và quản lý phiên.
# --------------------------------------------------------------------------------------------------

logger = logging.getLogger(__name__)
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
OAUTH_COOKIE_SECONDS = 300


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


class AuthService:
    """Xử lý callback Google OAuth, xoay refresh token và đăng xuất phiên."""

    REDIRECT_URI_COOKIE_NAME = "oauth_redirect_uri"

    def __init__(self, session: AsyncSession, response: Response | None = None) -> None:
        self.session = session
        self.response = response

    # ------------------------------------------------------------------ OAuth
    def build_google_auth_url(self, state: str, redirect_uri: str | None = None,
                              code_challenge: str | None = None) -> str:
        """URL đồng ý chỉ lấy danh tính: không có truy cập offline, token Google không bao giờ được lưu."""
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
            # Body phản hồi của nhà cung cấp có thể lặp lại chi tiết request; không đưa chúng vào phản hồi cho client.
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
        """Chuyển hướng tới Google với state chống CSRF và challenge PKCE giữ trong cookie ngắn hạn."""
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
        """Kiểm tra state CSRF, đổi code (kèm PKCE), upsert người dùng và cấp token HercFit."""
        if not state or not oauth_state or not hmac.compare_digest(state, oauth_state):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Invalid or missing OAuth state parameter (CSRF verification failed)")

        token_data = await self._exchange_google_code(code, redirect_uri=redirect_uri, code_verifier=code_verifier)
        userinfo = await self._fetch_google_user_info(token_data.get("access_token", ""))
        provider_user_id = str(userinfo.get("sub"))

        user = await User.upsert_from_google(self.session, userinfo)
        if not user.is_active:
            raise _unauthorized("User account is inactive")
        # Chỉ liên kết danh tính nhà cung cấp; access/refresh token của Google bị bỏ.
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

    # ---------------------------------------------------------------- Phiên
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
        """Một lần refresh đồng thời có thể trình token vừa được xoay một lát trước.

        Chỉ token ngay trước đó mới đủ điều kiện, chỉ trong một cửa sổ ngắn,
        và chỉ khi token thay thế của nó vẫn là đầu sống của họ token.
        """
        grace = settings.REFRESH_REUSE_GRACE_SECONDS
        return bool(
            grace > 0 and previous.revoked_at is not None and replacement is not None
            and (utc_now() - previous.revoked_at).total_seconds() <= grace
            and replacement.revoked_at is None and replacement.replaced_by_session_id is None
            and replacement.is_refresh_valid
        )

    async def refresh(self, refresh_token: str | None) -> Response:
        """Xoay một refresh token hợp lệ; chấp nhận một lần dùng lại đồng thời trong cửa sổ ân hạn."""
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
                # Trình duyệt đã giữ cookie thay thế từ request thắng cuộc;
                # trả lời không kèm Set-Cookie để giữ nguyên cookie đó.
                return self._token_response(user, self._access_token(user))
            # Dùng lại ngoài cửa sổ: coi là bị đánh cắp và thu hồi cả họ token.
            await AuthSession.revoke_replacement_chain(self.session, auth_session.replaced_by_session_id)
            await self.session.commit()  # Việc thu hồi phải tồn tại sau phản hồi 401.
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

    async def logout(self, refresh_token: str | None) -> LogoutResponse:
        """Thu hồi phiên refresh hiện tại và xoá cookie refresh token."""
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
    """Phụ thuộc FastAPI trả về AuthService đã cấu hình."""
    return AuthService(session=session, response=response)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


# --------------------------------------------------------------------------------------------------
# Quyền của chủ thể dữ liệu: xuất mọi thứ người dùng sở hữu, hoặc xoá tài khoản.
#
# Việc xoá sẽ xoá dòng users; khoá ngoại xoá dây chuyền tới mọi bảng sở hữu và các
# trigger ghi nhận knowledge graph phát sự kiện xoá, nên phép chiếu Neo4j được
# worker dọn. Quyền Google Health được thu hồi tại Google trước. Ảnh gắn với bản ghi của người dùng được xếp hàng
# để xoá trên Cloudinary trước. Dữ liệu hội thoại nằm trong service agent: backend gọi endpoint nội bộ của agent
# (purge_agent_conversations) trước khi xoá bất cứ thứ gì, và dừng nếu agent không xoá được.
# --------------------------------------------------------------------------------------------------

AGENT_CONVERSATIONS_PATH = "/internal/users/{user_id}/conversations"
# Xoá hội thoại có thể duyệt nhiều phiên: thời gian chờ rộng hơn lời gọi viết thông báo.
AGENT_PURGE_TIMEOUT_SECONDS = 30
ERASE_UNAVAILABLE = "Chưa xoá được lịch sử trò chuyện nên tài khoản chưa bị xoá. Vui lòng thử lại sau."

EXPORT_FORMAT_VERSION = 1
# Chỉ dùng SQL hằng; :uid là id của người dùng đã xác thực.
EXPORT_QUERIES: tuple[tuple[str, str], ...] = (
    ("profile", "SELECT id, email, fullname, nick_name, avatar_url, email_verified, last_login_at, is_onboarding, "
                "age, sex, personal_info, created_at, updated_at FROM users WHERE id = :uid"),
    ("linked_accounts", "SELECT provider, provider_user_id, created_at FROM oauth_accounts WHERE user_id = :uid"),
    ("sign_in_sessions", "SELECT created_at, expires_at, revoked_at FROM auth_sessions WHERE user_id = :uid ORDER BY created_at"),
    ("body_metrics", "SELECT * FROM body_metrics WHERE user_id = :uid ORDER BY recorded_at"),
    ("goals", "SELECT * FROM goals WHERE user_id = :uid ORDER BY created_at"),
    ("meals", "SELECT * FROM meals WHERE user_id = :uid ORDER BY consumed_at"),
    ("meal_items", "SELECT i.* FROM meal_items i JOIN meals m ON m.id = i.meal_id WHERE m.user_id = :uid "
                   "ORDER BY m.consumed_at, i.position"),
    ("trainings", "SELECT * FROM trainings WHERE user_id = :uid ORDER BY started_at"),
    ("training_items", "SELECT i.* FROM training_items i JOIN trainings t ON t.id = i.training_id "
                       "WHERE t.user_id = :uid ORDER BY t.started_at, i.position"),
    ("plans", "SELECT * FROM plans WHERE user_id = :uid ORDER BY created_at"),
    ("training_plans", "SELECT * FROM training_plans WHERE user_id = :uid ORDER BY created_at"),
    ("training_plan_entries", "SELECT e.* FROM training_plan_entries e JOIN training_plans p ON p.id = e.training_plan_id "
                              "WHERE p.user_id = :uid ORDER BY e.scheduled_date, e.position"),
    ("training_plan_items", "SELECT i.* FROM training_plan_items i JOIN training_plan_entries e ON e.id = i.entry_id "
                            "JOIN training_plans p ON p.id = e.training_plan_id WHERE p.user_id = :uid "
                            "ORDER BY e.scheduled_date, i.position"),
    ("custom_foods", "SELECT * FROM foods WHERE owner_user_id = :uid ORDER BY created_at"),
    ("custom_exercises", "SELECT * FROM exercises WHERE owner_user_id = :uid ORDER BY created_at"),
    # Thông tin xác thực nhà cung cấp không bao giờ được xuất; chỉ metadata của quyền đã cấp.
    ("health_connections", "SELECT provider, account_email, granted_scopes, status, share_with_assistant, consented_at, "
                           "timezone, provider_profile, last_sync_at, last_success_at, created_at "
                           "FROM health_connections WHERE user_id = :uid"),
    ("health_points", "SELECT data_type, kind, start_at, end_at, local_date, value, written_by_hercfit "
                      "FROM health_points WHERE user_id = :uid ORDER BY data_type, local_date, start_at"),
)
IMAGE_TABLES = (("meals", "user_id"), ("trainings", "user_id"), ("foods", "owner_user_id"), ("exercises", "owner_user_id"))


async def export_user_data(session, user_id) -> dict:
    data: dict = {"format_version": EXPORT_FORMAT_VERSION,
                  "exported_at": datetime.now(timezone.utc).isoformat(), "service": "hercfit-backend"}
    for name, sql in EXPORT_QUERIES:
        rows = (await session.execute(text(sql), {"uid": user_id})).mappings().all()
        data[name] = jsonable_encoder([dict(row) for row in rows])
    data["profile"] = data["profile"][0] if data["profile"] else None
    data["notes"] = ("Hội thoại với trợ lý được lưu ở dịch vụ agent; xuất hoặc xoá qua /api/v1/chat. "
                     "Bản ghi nhật ký là snapshot bất biến; các bản đã thay thế có is_active=false.")
    return data


async def purge_agent_conversations(user_id) -> dict:
    """Xoá mọi cuộc trò chuyện của người dùng ở service agent (endpoint nội bộ ký HMAC). Không xoá được thì 503 để bên
    gọi chưa xoá gì ở backend: không bao giờ còn hội thoại mồ côi sau khi tài khoản đã mất."""
    secret = settings.AGENT_SERVICE_SECRET.get_secret_value() if settings.AGENT_SERVICE_SECRET else ""
    if not settings.AGENTIC_INTERNAL_URL or not secret:
        raise HTTPException(503, ERASE_UNAVAILABLE)
    path = AGENT_CONVERSATIONS_PATH.format(user_id=user_id)
    headers = {service_auth.HEADER: service_auth.sign(secret, "DELETE", path, str(user_id))}
    try:
        async with httpx.AsyncClient(base_url=settings.AGENTIC_INTERNAL_URL,
                                     timeout=AGENT_PURGE_TIMEOUT_SECONDS) as client:
            response = await client.delete(path, headers=headers)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("agent_conversation_purge_failed error=%s", type(exc).__name__)
        raise HTTPException(503, ERASE_UNAVAILABLE) from None


async def erase_user(session, user_id) -> dict:
    """Xoá cứng tài khoản trong transaction của bên gọi; trả về số đếm cho biên nhận."""
    from domains.health_records import ports

    # Thu hồi quyền tại nhà cung cấp trước (cố gắng hết mức); bản thân các dòng sẽ bị xoá dây chuyền.
    await ports.before_account_erasure(session, user_id)
    images = 0
    if settings.CLOUDINARY_CLOUD_NAME:
        for table, owner in IMAGE_TABLES:
            result = await session.execute(text(
                f"INSERT INTO image_cleanup (public_id, cloud_name) SELECT image_public_id, :cloud FROM {table} "
                f"WHERE {owner} = :uid AND image_public_id IS NOT NULL ON CONFLICT (public_id) DO NOTHING"
            ), {"uid": user_id, "cloud": settings.CLOUDINARY_CLOUD_NAME})
            images += result.rowcount or 0
    counts = {}
    for name in ("meals", "trainings", "body_metrics", "goals", "health_points", "google_pushes"):
        counts[name] = (await session.execute(text(f"SELECT count(*) FROM {name} WHERE user_id = :uid"),
                                              {"uid": user_id})).scalar_one()
    deleted = (await session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})).rowcount
    return {"erased": bool(deleted), "records": counts, "images_queued_for_removal": images}


# --------------------------------------------------------------------------------------------------
# Các use case hồ sơ, lịch sử số đo và mục tiêu đã xác thực.
#
# Model sở hữu luật lưu trữ; transaction của request sở hữu commit/rollback.
# --------------------------------------------------------------------------------------------------

class UserDataService(UserService):

    async def update_profile(self, payload: UserUpdate) -> User:
        return require_found(
            await User.update_profile(self.session, self.user_id, payload), "User",
        )

    async def merge_personal_info(self, values: JsonObject) -> User:
        return require_found(
            await User.update_personal_info(self.session, self.user_id, values), "User",
        )

    async def onboard(self, payload: OnboardingInput) -> User:
        return require_found(
            await User.complete_onboarding(self.session, self.user_id, payload), "User",
        )

    async def delete_profile(self) -> None:
        require_found(await User.deactivate_profile(self.session, self.user_id), "User")

    # Số đo Google có (ghi xuyên qua khi đã kết nối): cột HercFit → loại bản ghi Google.
    GOOGLE_FIELDS = (("weight_kg", "weight"), ("height_cm", "height"), ("body_fat_pct", "body-fat"))
    LOCAL_FIELDS = ("muscle_mass_kg", "chest_cm", "waist_cm", "hip_cm")

    async def create_metric(self, payload: BodyMetricCreate) -> Any:
        """Đã kết nối Google: cân nặng / chiều cao / mỡ lưu vào health_points (bản HercFit) rồi được đẩy lên Google
        sau commit; khối cơ và chỉ số khác Google không có vẫn lưu trong body_metrics. Chưa kết nối: lưu như trước."""
        from domains.body.services import Reading
        from domains.health_records import ports

        data = BodyMetricCreate.model_validate(payload)
        written: dict[str, Any] = {}
        for column, kind in self.GOOGLE_FIELDS:
            value = getattr(data, column)
            if value is None:
                continue
            result = await ports.write(self.session, self.user_id, kind, {
                "value": float(value), "measured_at": data.recorded_at.isoformat()})
            if result is None:  # chưa kết nối Google
                return await BodyMetric.create_snapshot(self.session, user_id=self.user_id, payload=data)
            written[column] = result
        # Google không có khối cơ và vòng đo: giữ trong HercFit.
        local = {field: getattr(data, field) for field in self.LOCAL_FIELDS if getattr(data, field) is not None}
        row = None
        if local:
            row = await BodyMetric.create(self.session, {"user_id": self.user_id, "recorded_at": data.recorded_at,
                                                         **local, "additional_metrics": data.additional_metrics})
        # id luôn là của một bản ghi có thật (điểm Google đầu tiên đã ghi, hoặc dòng HercFit), không bao giờ ngẫu nhiên.
        record_id = next((written[column].get("id") for column, _kind in self.GOOGLE_FIELDS
                          if (written.get(column) or {}).get("id")), None) or (row.id if row is not None else None)
        now = datetime.now(timezone.utc)
        return Reading(id=record_id, user_id=self.user_id,
                       recorded_at=data.recorded_at, created_at=now, updated_at=now, source="MANUAL",
                       weight_kg=data.weight_kg, height_cm=data.height_cm, body_fat_pct=data.body_fat_pct,
                       muscle_mass_kg=data.muscle_mass_kg, chest_cm=data.chest_cm, waist_cm=data.waist_cm,
                       hip_cm=data.hip_cm, additional_metrics=data.additional_metrics, written_by_hercfit=True)

    async def list_metrics(self, options: BodyMetricQuery) -> list[Any]:
        return await BodyMetric.list_for_user(
            self.session, user_id=self.user_id, **options.model_dump(),
        )

    async def latest_metric(self, field: LatestBodyMetricField | None = None) -> Any:
        return require_found(
            await BodyMetric.latest(self.session, self.user_id, field or "weight_kg"), "Body metric",
        )

    async def _google_reading(self, metric_id: UUID):
        """Số đo trên Google có id này (bản sao trong health_points), nếu có."""
        from domains.body import services as readings

        found = [item for item in await readings.google(self.session, self.user_id, limit=10_000)
                 if item.id == metric_id]
        return found[0] if found else None

    async def get_metric(self, metric_id: UUID) -> Any:
        metric = await BodyMetric.get_for_user(self.session, metric_id, user_id=self.user_id)
        return require_found(metric or await self._google_reading(metric_id), "Body metric")

    async def replace_metric(self, metric_id: UUID, payload: BodyMetricCreate) -> Any:
        from domains.health_records import ports

        reading = await self._google_reading(metric_id)
        if reading is None:
            return require_found(await BodyMetric.replace_for_user(
                self.session, metric_id, user_id=self.user_id, payload=payload,
            ), "Body metric")
        data = BodyMetricCreate.model_validate(payload)
        column, kind = next((column, kind) for column, kind in self.GOOGLE_FIELDS
                            if getattr(reading, column) is not None)
        if getattr(data, column) is None:
            raise HTTPException(422, f"{column} is required to edit this measurement")
        await ports.write(self.session, self.user_id, kind, {
            "value": float(getattr(data, column)), "measured_at": data.recorded_at.isoformat()}, point_id=metric_id)
        return require_found(await self._google_reading(metric_id), "Body metric")

    async def delete_metric(self, metric_id: UUID) -> None:
        from domains.health_records import ports

        reading = await self._google_reading(metric_id)
        if reading is None:
            require_found(await BodyMetric.soft_delete_for_user(
                self.session, metric_id, user_id=self.user_id,
            ), "Body metric")
            return
        kind = next(kind for column, kind in self.GOOGLE_FIELDS if getattr(reading, column) is not None)
        await ports.write(self.session, self.user_id, kind, point_id=metric_id, delete=True)

    async def confirm_goal(self, payload: GoalCreate) -> Goal:
        # Mục tiêu đã xác nhận chuyển sang IN_PROGRESS; bản nháp vẫn ở phía client.
        return await Goal.create_for_user(self.session, user_id=self.user_id, payload=payload)

    async def list_goals(self, options: Pagination) -> list[Goal]:
        return await Goal.list_for_user(self.session, user_id=self.user_id, **options.model_dump())

    async def current_goal(self) -> Goal:
        return require_found(
            await Goal.get_current_for_user(self.session, user_id=self.user_id), "Goal",
        )

    async def get_goal(self, goal_id: UUID) -> Goal:
        return require_found(
            await Goal.get_for_user(self.session, goal_id, user_id=self.user_id), "Goal",
        )

    async def update_goal(self, goal_id: UUID, payload: GoalUpdateRequest) -> Goal:
        try:
            goal = await Goal.update_for_user(
                self.session, goal_id, user_id=self.user_id,
                payload=payload.to_payload(), expected_version_id=payload.expected_version_id,
            )
        except ValidationError as exc:
            # Bao gồm kiểm tra với các ngày đã lưu trong database.
            raise request_validation_error(exc, "body") from exc
        return require_found(goal, "Goal")

    async def complete_goal(self, goal_id: UUID) -> Goal:
        return require_found(
            await Goal.complete_for_user(self.session, goal_id, user_id=self.user_id), "Goal",
        )

    async def cancel_goal(self, goal_id: UUID) -> Goal:
        return require_found(
            await Goal.cancel_for_user(self.session, goal_id, user_id=self.user_id), "Goal",
        )

    async def delete_goal(self, goal_id: UUID) -> None:
        require_found(
            await Goal.soft_delete_for_user(self.session, goal_id, user_id=self.user_id), "Goal",
        )
