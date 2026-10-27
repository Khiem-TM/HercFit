from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any
from collections.abc import Mapping

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.basemodel import BaseModel, utc_now
from schemas.auth_session import AuthSessionCreate, AuthSessionRevoke

if TYPE_CHECKING:
    from models.user import User


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
        # Serialize rotation/revocation of the same refresh token.
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
