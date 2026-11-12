from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from domains.identity.schemas.user import GoogleProfile, OnboardingInput, UserUpdate
from domains.shared.models.basemodel import BaseModel, utc_now
from domains.shared.models.domain import try_lock_user
from domains.shared.schemas.common import JsonObjectInput

if TYPE_CHECKING:
    from domains.body.models.body_metrics import BodyMetric
    from domains.catalog.models.foods import FoodItem
    from domains.goals_plans.models.goal import Goal
    from domains.identity.models.auth_session import AuthSession
    from domains.identity.models.oauth_account import OAuthAccount


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
        from domains.identity.models.auth_session import AuthSession

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
        from domains.body.models.body_metrics import BodyMetric
        from domains.goals_plans.models.goal import Goal

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
