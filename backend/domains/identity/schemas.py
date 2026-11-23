"""Schema Pydantic của miền danh tính và quyền riêng tư."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, EmailStr, Field, HttpUrl, PlainSerializer, SecretStr

from domains.body.schemas import BodyMetricCreate
from domains.goals_plans.schemas import GoalCreate
from domains.shared.schemas import (
    EntityRead,
    InputSchema,
    JsonObject,
    Name,
    NonBlank,
    PartialSchema,
)

# --------------------------------------------------------------------------------------------------
# auth_session
# --------------------------------------------------------------------------------------------------

class AuthSessionCreate(InputSchema):
    user_id: UUID
    refresh_token_hash: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$", repr=False)]
    expires_at: AwareDatetime


class AuthSessionRevoke(InputSchema):
    replaced_by_session_id: UUID | None = None


class LogoutResponse(InputSchema):
    message: str = "Logged out successfully"


# --------------------------------------------------------------------------------------------------
# oauth_account
# --------------------------------------------------------------------------------------------------

Provider = Annotated[NonBlank, Field(max_length=50)]


class OAuthTokenUpdate(InputSchema):
    model_config = ConfigDict(extra="ignore")
    access_token: SecretStr | None = None
    refresh_token: SecretStr | None = None
    expires_in: Annotated[int, Field(ge=0)] | None = None


class OAuthAccountCreate(InputSchema):
    user_id: UUID
    provider: Provider = "google"
    provider_user_id: Name
    access_token: SecretStr | None = None
    refresh_token: SecretStr | None = None
    token_expires_at: AwareDatetime | None = None

    def to_payload(self):
        values = super().to_payload()
        for field in ("access_token", "refresh_token"):
            if values.get(field) is not None:
                values[field] = values[field].get_secret_value()
        return values


# --------------------------------------------------------------------------------------------------
# user
# --------------------------------------------------------------------------------------------------

Email = Annotated[EmailStr, Field(max_length=255)]
URL = Annotated[HttpUrl, PlainSerializer(str, return_type=str)]
Age = Annotated[int, Field(strict=True, ge=1, le=120)]
Nickname = Annotated[str, Field(max_length=100)]
# Giới tính sinh học là tuỳ chọn và chỉ dùng cho phương trình năng lượng (Mifflin-St Jeor).
Sex = Literal["MALE", "FEMALE"]


class UserCreate(InputSchema):
    email: Email
    fullname: Name
    nick_name: Nickname | None = None
    avatar_url: URL | None = None
    age: Age | None = None
    sex: Sex | None = None
    personal_info: JsonObject = Field(default_factory=dict)


class UserUpdate(PartialSchema):
    non_nullable = frozenset({"fullname", "personal_info"})
    fullname: Name | None = None
    nick_name: Nickname | None = None
    avatar_url: URL | None = None
    age: Age | None = None
    sex: Sex | None = None
    personal_info: JsonObject = Field(default_factory=dict)


class OnboardingInput(UserUpdate):
    non_nullable = UserUpdate.non_nullable | {"body_metric", "goal"}
    body_metric: BodyMetricCreate | None = None
    goal: GoalCreate | None = None


class GoogleProfile(InputSchema):
    # Nhà cung cấp OAuth có thể thêm claim mà ứng dụng không dùng.
    model_config = ConfigDict(extra="ignore")
    email: Email
    name: Name | None = None
    picture: URL | None = None
    email_verified: bool = False


class UserRead(UserCreate, EntityRead):
    email_verified: bool
    last_login_at: AwareDatetime | None
    is_onboarding: bool
