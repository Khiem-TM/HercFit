from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.basemodel import BaseModel, utc_now

if TYPE_CHECKING:
    from models.auth_session import AuthSession
    from models.oauth_account import OAuthAccount


class User(BaseModel):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_email_ci", text("lower(email)"), unique=True),
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

    # Fitness profile fields (HercFit)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    fitness_goal: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relationships
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
    async def get_by_email(cls, session: AsyncSession, email: str) -> User | None:
        return await cls.get_one(
            session,
            email=email,
            include_inactive=True,
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
    async def complete_onboarding(
        cls,
        session: AsyncSession,
        user_id: uuid.UUID,
        values: Mapping[str, Any],
    ) -> User | None:
        allowed_fields = {
            "fullname",
            "nick_name",
            "avatar_url",
            "age",
            "height_cm",
            "fitness_goal",
        }
        payload = {
            key: value
            for key, value in values.items()
            if key in allowed_fields
        }
        payload["is_onboarding"] = True

        return await cls.update_one(session, user_id, payload)