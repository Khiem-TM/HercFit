"""Pydantic schemas validating authentication context for tool invocations."""

from pydantic import BaseModel, Field


class AuthContextInput(BaseModel):
    """Authentication context injected into backend-facing tools."""

    user_id: str | None = Field(
        default=None,
        description="Authenticated user identifier.",
    )
    auth_token: str | None = Field(
        default=None,
        description="Bearer JWT or API token used to authenticate with the HercFit Backend.",
    )


class TokenVerifyOutput(BaseModel):
    """Validation result of an authentication token."""

    is_valid: bool
    user_id: str | None = None
    scopes: list[str] = Field(default_factory=list)

