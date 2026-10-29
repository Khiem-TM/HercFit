from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, EmailStr, Field, HttpUrl, PlainSerializer

from schemas.body_metrics import BodyMetricCreate
from schemas.common import EntityRead, InputSchema, JsonObject, Name, PartialSchema
from schemas.goal import GoalCreate

Email = Annotated[EmailStr, Field(max_length=255)]
URL = Annotated[HttpUrl, PlainSerializer(str, return_type=str)]
Age = Annotated[int, Field(strict=True, ge=1, le=120)]
Nickname = Annotated[str, Field(max_length=100)]
# Biological sex is optional and used only by energy equations (Mifflin-St Jeor).
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
    # OAuth providers may add claims that the application does not consume.
    model_config = ConfigDict(extra="ignore")
    email: Email
    name: Name | None = None
    picture: URL | None = None
    email_verified: bool = False


class UserRead(UserCreate, EntityRead):
    email_verified: bool
    last_login_at: AwareDatetime | None
    is_onboarding: bool
