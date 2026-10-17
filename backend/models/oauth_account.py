from datetime import datetime, timedelta
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.basemodel import (
    BaseModel,
    utc_now,
)
from schemas.oauth_account import OAuthAccountCreate, OAuthTokenUpdate

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
    async def get_by_user_provider(
        cls,
        session: AsyncSession,
        user_id: PyUUID,
        provider: str,
        *,
        include_inactive: bool = False,
    ) -> "OAuthAccount | None":
        return await cls.get_one(
            session,
            user_id=user_id,
            provider=provider,
            include_inactive=include_inactive,
        )

    @classmethod
    async def upsert_google_account(
        cls,
        session: AsyncSession,
        user_id: PyUUID,
        provider_user_id: str,
        token_data: dict[str, Any],
    ) -> "OAuthAccount":
        account_data = OAuthAccountCreate(user_id=user_id, provider_user_id=provider_user_id)
        token_data = OAuthTokenUpdate.model_validate(token_data)
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

        oauth_account.update_tokens(token_data)
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
