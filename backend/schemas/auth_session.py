from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field

from schemas.common import EntityRead, InputSchema


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
