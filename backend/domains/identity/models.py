"""Model ORM của miền danh tính và quyền riêng tư."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from domains.identity.schemas import (
    AuthSessionCreate,
    AuthSessionRevoke,
    GoogleProfile,
    OAuthAccountCreate,
    OAuthTokenUpdate,
    OnboardingInput,
    UserUpdate,
)
from domains.shared.models import BaseModel, try_lock_user, utc_now
from domains.shared.schemas import JsonObjectInput

# --------------------------------------------------------------------------------------------------
# auth_session
# --------------------------------------------------------------------------------------------------

class AuthSession(BaseModel):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "replaced_by_session_id IS NULL OR replaced_by_session_id <> id",
            name="ck_auth_sessions_replacement_not_self",
        ),
        UniqueConstraint(
            "replaced_by_session_id",
            name="uq_auth_sessions_replaced_by_session_id",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    refresh_token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replaced_by_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="auth_sessions")
    replaced_by: Mapped["AuthSession | None"] = relationship(
        "AuthSession",
        remote_side="AuthSession.id",
        foreign_keys=[replaced_by_session_id],
        back_populates="replaces",
        uselist=False,
    )
    replaces: Mapped["AuthSession | None"] = relationship(
        "AuthSession",
        foreign_keys=[replaced_by_session_id],
        back_populates="replaced_by",
        uselist=False,
    )

    @property
    def is_refresh_valid(self) -> bool:
        return bool(
            self.is_active
            and self.revoked_at is None
            and self.expires_at > utc_now()
        )

    @classmethod
    async def create_session(
        cls, session: AsyncSession, payload: AuthSessionCreate | Mapping[str, Any],
    ) -> AuthSession:
        return await cls.create(session, AuthSessionCreate.model_validate(payload).to_payload())

    @classmethod
    async def get_by_refresh_token_hash(
        cls,
        session: AsyncSession,
        refresh_token_hash: str,
    ) -> AuthSession | None:
        # Tuần tự hoá việc xoay/thu hồi cùng một refresh token.
        return (await session.execute(
            select(cls).where(cls.refresh_token_hash == refresh_token_hash, cls.is_active.is_(True))
            .with_for_update().execution_options(populate_existing=True)
        )).scalar_one_or_none()

    @classmethod
    async def get_for_update(cls, session: AsyncSession, session_id: uuid.UUID | None) -> AuthSession | None:
        if session_id is None:
            return None
        return (await session.execute(
            select(cls).where(cls.id == session_id).with_for_update().execution_options(populate_existing=True)
        )).scalar_one_or_none()

    async def revoke(
        self,
        session: AsyncSession,
        replaced_by_session_id: uuid.UUID | None = None,
    ) -> None:
        replacement = AuthSessionRevoke(replaced_by_session_id=replaced_by_session_id)
        self.revoked_at = utc_now()
        self.replaced_by_session_id = replacement.replaced_by_session_id
        session.add(self)

    @classmethod
    async def revoke_replacement_chain(
        cls,
        session: AsyncSession,
        session_id: uuid.UUID | None,
    ) -> None:
        while session_id:
            auth_session = (await session.execute(
                select(cls).where(cls.id == session_id).with_for_update()
                .execution_options(populate_existing=True)
            )).scalar_one_or_none()
            if auth_session is None:
                return

            next_session_id = auth_session.replaced_by_session_id
            if auth_session.revoked_at is None:
                await auth_session.revoke(session)

            session_id = next_session_id


# --------------------------------------------------------------------------------------------------
# Những gì người dùng cho phép HercFit làm với dữ liệu sức khoẻ của họ, thành một bản ghi riêng.
#
# user_consents giữ quyết định hiện tại theo (mục đích, nhóm dữ liệu); consent_events
# là lịch sử chỉ-ghi-thêm. Cổng của knowledge graph (kg_device_consent) cũng đọc
# user_consents, nên lệnh đọc SQL, tool và graph đều theo một quyết định.
#
# `version` tăng ở mọi thay đổi của một người dùng (trên mọi mục đích và nhóm), để
# job hay ngữ cảnh cache dựng theo phiên bản cũ hơn bị nhận ra là đã cũ.
# --------------------------------------------------------------------------------------------------

class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (
        CheckConstraint("purpose IN ('assistant', 'proactive')", name="ck_user_consents_purpose"),
        CheckConstraint("data_group IN ('device', 'sensitive')", name="ck_user_consents_data_group"),
        CheckConstraint("version >= 1", name="ck_user_consents_version"),
    )

    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            primary_key=True)
    purpose: Mapped[str] = mapped_column(String(30), primary_key=True)
    data_group: Mapped[str] = mapped_column(String(30), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ConsentEvent(Base):
    __tablename__ = "consent_events"
    __table_args__ = (
        CheckConstraint("actor IN ('USER', 'SYSTEM', 'MIGRATION')", name="ck_consent_events_actor"),
        Index("ix_consent_events_user", "user_id", "occurred_at"),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                       server_default=text("gen_random_uuid()"))
    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                            nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    data_group: Mapped[str] = mapped_column(String(30), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# --------------------------------------------------------------------------------------------------
# oauth_account
# --------------------------------------------------------------------------------------------------

class OAuthAccount(BaseModel):
    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_oauth_accounts_provider_user",
        ),
        UniqueConstraint(
            "user_id",
            "provider",
            name="uq_oauth_accounts_user_provider",
        ),
    )

    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(
        String(50),
        default="google",
        server_default="google",
        nullable=False,
    )
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="oauth_accounts")

    @classmethod
    async def get_by_provider_user_id(
        cls,
        session: AsyncSession,
        provider: str,
        provider_user_id: str,
        *,
        include_inactive: bool = False,
    ) -> "OAuthAccount | None":
        return await cls.get_one(
            session,
            provider=provider,
            provider_user_id=provider_user_id,
            include_inactive=include_inactive,
        )

    @classmethod
    async def upsert_google_account(
        cls,
        session: AsyncSession,
        user_id: PyUUID,
        provider_user_id: str,
        token_data: dict[str, Any] | None = None,
    ) -> "OAuthAccount":
        """Liên kết danh tính Google. HercFit chỉ cần biết người dùng là ai, nên
        token nhà cung cấp không được lưu trừ khi bên gọi truyền tường minh."""
        account_data = OAuthAccountCreate(user_id=user_id, provider_user_id=provider_user_id)
        oauth_account = await cls.get_by_provider_user_id(
            session,
            provider="google",
            provider_user_id=account_data.provider_user_id,
        )
        if oauth_account is None: 
            oauth_account = cls(
                user_id=account_data.user_id,
                provider="google",
                provider_user_id=account_data.provider_user_id,
            )
            session.add(oauth_account)

        if token_data:
            oauth_account.update_tokens(token_data)
        else:
            # Xoá thông tin xác thực mà các phiên bản trước đã lưu ở lần đăng nhập kế tiếp.
            oauth_account.access_token = None
            oauth_account.refresh_token = None
            oauth_account.token_expires_at = None
        return oauth_account

    def update_tokens(self, token_data: OAuthTokenUpdate | dict[str, Any]) -> None:
        tokens = OAuthTokenUpdate.model_validate(token_data)
        access_token = tokens.access_token
        if access_token:
            self.access_token = access_token.get_secret_value()
        refresh_token = tokens.refresh_token
        if refresh_token:
            self.refresh_token = refresh_token.get_secret_value()
        expires_in = tokens.expires_in
        if expires_in is not None:
            self.token_expires_at = utc_now() + timedelta(seconds=expires_in)


# --------------------------------------------------------------------------------------------------
# user
# --------------------------------------------------------------------------------------------------

if TYPE_CHECKING:
    from domains.body.models import BodyMetric
    from domains.catalog.models import FoodItem
    from domains.goals_plans.models import Goal


class User(BaseModel):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_email_ci", text("lower(email)"), unique=True),
        CheckConstraint("jsonb_typeof(personal_info) = 'object'", name="ck_users_personal_info_object"),
        CheckConstraint("sex IS NULL OR sex IN ('MALE', 'FEMALE')", name="ck_users_sex"),
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    fullname: Mapped[str] = mapped_column(String(255), nullable=False)
    nick_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_onboarding: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    # Thông tin cá nhân ổn định. Số đo và mục tiêu có lịch sử riêng.
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Giới tính sinh học tuỳ chọn, chỉ là đầu vào của các phương trình BMR.
    sex: Mapped[str | None] = mapped_column(String(10), nullable=True)
    personal_info: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), default=dict, server_default=text("'{}'::jsonb"), nullable=False,
    )

    # Quan hệ
    body_metrics: Mapped[list[BodyMetric]] = relationship(
        "BodyMetric",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    goals: Mapped[list[Goal]] = relationship(
        "Goal",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    custom_foods: Mapped[list[FoodItem]] = relationship(
        "FoodItem",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        "OAuthAccount",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    auth_sessions: Mapped[list[AuthSession]] = relationship(
        "AuthSession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @classmethod
    async def get_by_email_ci(
        cls,
        session: AsyncSession,
        email: str,
        *,
        include_inactive: bool = False,
    ) -> User | None:
        query = select(cls).where(func.lower(cls.email) == email.lower())
        query = cls.apply_active_scope(query, include_inactive=include_inactive)

        result = await session.execute(query)
        return result.scalar_one_or_none()

    def apply_google_profile(self, userinfo: dict[str, Any]) -> None:
        userinfo = GoogleProfile.model_validate(userinfo).model_dump(mode="python", exclude_unset=True)
        email = userinfo.get("email") or self.email
        self.fullname = userinfo.get("name") or self.fullname or email
        self.avatar_url = userinfo.get("picture") or self.avatar_url
        self.last_login_at = utc_now()
        if userinfo.get("email_verified") is not None:
            self.email_verified = bool(userinfo["email_verified"])

    @classmethod
    async def upsert_from_google(
        cls,
        session: AsyncSession,
        userinfo: dict[str, Any],
    ) -> User:
        userinfo = GoogleProfile.model_validate(userinfo).model_dump(mode="python")
        email = userinfo["email"]
        fullname = userinfo.get("name") or email
        avatar_url = userinfo.get("picture")
        email_verified = bool(userinfo.get("email_verified", True))

        user = await cls.get_by_email_ci(session, email, include_inactive=True)
        if user is None:
            user = await cls.create(
                session,
                {
                    "email": email,
                    "fullname": fullname,
                    "nick_name": fullname,
                    "avatar_url": avatar_url,
                    "email_verified": email_verified,
                    "last_login_at": utc_now(),
                    "is_onboarding": False,
                },
            )
        else:
            user.apply_google_profile(userinfo)
            session.add(user)

        return user

    @classmethod
    async def update_personal_info(
        cls, session: AsyncSession, user_id: uuid.UUID, values: Mapping[str, Any],
    ) -> User | None:
        """Gộp các nhóm cấp cao nhất, thay toàn bộ giá trị của từng nhóm được truyền."""
        values = JsonObjectInput.model_validate(values).root
        user = await try_lock_user(session, user_id)
        if user is None:
            return None
        user.personal_info = {**user.personal_info, **values}
        await session.flush()
        await session.refresh(user)
        return user

    @classmethod
    async def update_profile(
        cls, session: AsyncSession, user_id: uuid.UUID,
        payload: UserUpdate | Mapping[str, Any],
    ) -> User | None:
        values = UserUpdate.model_validate(payload).to_payload()
        user = await try_lock_user(session, user_id)
        if user is None:
            return None
        for key, value in values.items():
            setattr(user, key, value)
        await session.flush()
        await session.refresh(user)
        return user

    @classmethod
    async def deactivate_profile(cls, session: AsyncSession, user_id: uuid.UUID) -> User | None:
        """Xoá mềm tài khoản và thu hồi các phiên refresh trong cùng transaction."""
        from domains.identity.models import AuthSession

        user = await try_lock_user(session, user_id)
        if user is None:
            return None
        sessions = await AuthSession.get_list(session, user_id=user_id)
        for auth_session in sessions:
            if auth_session.revoked_at is None:
                await auth_session.revoke(session)
        user.is_active = False
        await session.flush()
        return user

    @classmethod
    async def complete_onboarding(
        cls,
        session: AsyncSession,
        user_id: uuid.UUID,
        values: OnboardingInput | Mapping[str, Any],
    ) -> User | None:
        """Lưu hồ sơ, số đo ban đầu (tuỳ chọn) và mục tiêu trong một savepoint.

        body_metric và goal nhận payload tạo có phạm vi tương ứng.
        goal cần title/start_date và có thể kèm ngữ cảnh và chỉ tiêu tự do.
        Bên gọi vẫn sở hữu transaction bên ngoài và phải commit khi thành công.
        """
        from domains.body.models import BodyMetric
        from domains.goals_plans.models import Goal

        values = OnboardingInput.model_validate(values).to_payload()

        async with session.begin_nested():
            user = await try_lock_user(session, user_id)
            if user is None:
                return None
            if "personal_info" in values:
                user.personal_info = {**user.personal_info, **values["personal_info"]}
            for key in ("fullname", "nick_name", "avatar_url", "age", "sex"):
                if key in values:
                    setattr(user, key, values[key])
            if "body_metric" in values:
                await BodyMetric.create_snapshot(session, user_id=user_id, payload=values["body_metric"])
            if "goal" in values:
                await Goal.create_for_user(session, user_id=user_id, payload=values["goal"])
            user.is_onboarding = True
            await session.flush()
            await session.refresh(user)
        return user
