from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field

from schemas.common import EntityRead, InputSchema
from schemas.user import UserRead


class AuthSessionCreate(InputSchema):
    user_id: UUID
    refresh_token_hash: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$", repr=False)]
    expires_at: AwareDatetime


class AuthSessionRevoke(InputSchema):
    replaced_by_session_id: UUID | None = None


class AuthSessionRead(EntityRead):
    user_id: UUID
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None
    replaced_by_session_id: UUID | None


class LogoutResponse(InputSchema):
    message: str = "Logged out successfully"


class TokenResponse(InputSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead
