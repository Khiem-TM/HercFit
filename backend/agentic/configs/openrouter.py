"""Thư mục gốc cố định và thông tin xác thực OpenRouter dùng chung (local và Compose đọc .env của backend rồi của agent)."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentic.services.providers.openrouter_policy import BASE_URL

# --------------------------------------------------------------------------------------------------
# Thư mục tài nguyên cố định, không phụ thuộc thư mục làm việc của tiến trình.
# --------------------------------------------------------------------------------------------------

AGENTIC_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = AGENTIC_ROOT.parent


class OpenRouterSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_ROOT / ".env"), str(AGENTIC_ROOT / ".env")),
        extra="ignore",
        env_ignore_empty=True,
    )
    OPENROUTER_API_KEY: SecretStr | None = None
    OPENROUTER_BASE_URL: str = BASE_URL
