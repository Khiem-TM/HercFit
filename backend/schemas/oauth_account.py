from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, SecretStr

from schemas.common import EntityRead, InputSchema, Name, NonBlank

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


class OAuthAccountRead(EntityRead):
    user_id: UUID
    provider: str
    provider_user_id: str
    token_expires_at: AwareDatetime | None
