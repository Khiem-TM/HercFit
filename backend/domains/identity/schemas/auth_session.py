from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field

from domains.shared.schemas.common import InputSchema


class AuthSessionCreate(InputSchema):
    user_id: UUID
    refresh_token_hash: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$", repr=False)]
    expires_at: AwareDatetime


class AuthSessionRevoke(InputSchema):
    replaced_by_session_id: UUID | None = None


class LogoutResponse(InputSchema):
    message: str = "Logged out successfully"
