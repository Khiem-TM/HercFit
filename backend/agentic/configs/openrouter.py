"""Shared OpenRouter credentials; local and Compose use backend then agent env."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentic.configs.paths import AGENTIC_ROOT, BACKEND_ROOT
from agentic.services.providers.openrouter_policy import BASE_URL


class OpenRouterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_ROOT / ".env"), str(AGENTIC_ROOT / ".env")),
        extra="ignore",
        env_ignore_empty=True,
    )
    OPENROUTER_API_KEY: SecretStr | None = None
    OPENROUTER_BASE_URL: str = BASE_URL
