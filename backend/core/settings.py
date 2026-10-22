# Đọc biến môi trường từ .env

from enum import StrEnum

from dotenv import find_dotenv
from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    def to_logging_level(self) -> int:
        """Convert to Python logging level constant."""
        import logging

        mapping = {
            LogLevel.DEBUG: logging.DEBUG,
            LogLevel.INFO: logging.INFO,
            LogLevel.WARNING: logging.WARNING,
            LogLevel.ERROR: logging.ERROR,
            LogLevel.CRITICAL: logging.CRITICAL,
        }
        return mapping[self]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=find_dotenv(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        validate_default=False,
    )
    MODE: str | None = None

    HOST: str = "0.0.0.0"
    PORT: int = 8080
    GRACEFUL_SHUTDOWN_TIMEOUT: int = 30
    LOG_LEVEL: LogLevel = LogLevel.WARNING

    AUTH_SECRET: SecretStr | None = None

    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    JWT_SECRET_KEY: SecretStr | None = None
    JWT_SECRET: SecretStr | None = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Google OAuth
    GOOGLE_OAUTH_CLIENT_ID: str | None = None
    GOOGLE_OAUTH_CLIENT_SECRET: SecretStr | None = None
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:5173/auth/callback"
    OAUTH_ALLOWED_REDIRECT_URIS: list[str] = [
        "http://localhost:5173/auth/callback",
        "http://localhost:5174/auth/callback",
    ]
    FRONTEND_URL: str = "http://localhost:5173"

    # PostgreSQL Configuration
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: SecretStr | None = None
    POSTGRES_HOST: str | None = None
    POSTGRES_PORT: int | None = None
    POSTGRES_DB: str | None = None
    POSTGRES_APPLICATION_NAME: str = "hercfit-backend"
    POSTGRES_MIN_CONNECTIONS_PER_POOL: int = 1
    POSTGRES_MAX_CONNECTIONS_PER_POOL: int = 1
    POSTGRES_POOL_TIMEOUT: float = 30.0
    POSTGRES_CONNECT_TIMEOUT: float = 10.0

    @property
    def jwt_secret_value(self) -> str:
        secret = self.JWT_SECRET_KEY or self.JWT_SECRET or self.AUTH_SECRET
        if not secret:
            raise ValueError("JWT secret is not configured in settings or .env")
        return secret.get_secret_value()

    @property
    def google_client_secret_value(self) -> str:
        if not self.GOOGLE_OAUTH_CLIENT_SECRET:
            raise ValueError("GOOGLE_OAUTH_CLIENT_SECRET is not configured in settings or .env")
        return self.GOOGLE_OAUTH_CLIENT_SECRET.get_secret_value()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def BASE_URL(self) -> str:
        return f"http://{self.HOST}:{self.PORT}"

    def is_dev(self) -> bool:
        return self.MODE == "dev"

    def resolve_oauth_redirect_uri(
        self,
        requested_uri: str | None = None,
        referer: str | None = None,
    ) -> str:
        from urllib.parse import urlparse
        from fastapi import HTTPException

        allowed = list(dict.fromkeys([
            *(self.OAUTH_ALLOWED_REDIRECT_URIS or []),
            self.GOOGLE_OAUTH_REDIRECT_URI,
        ]))

        if requested_uri:
            if requested_uri in allowed:
                return requested_uri
            raise HTTPException(
                status_code=400,
                detail=f"Redirect URI '{requested_uri}' is not in OAUTH_ALLOWED_REDIRECT_URIS",
            )

        if referer:
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc:
                host = parsed.hostname or ""
                if host == "127.0.0.1":
                    netloc = f"localhost:{parsed.port}" if parsed.port else "localhost"
                else:
                    netloc = parsed.netloc
                candidate = f"{parsed.scheme}://{netloc}/auth/callback"
                if candidate in allowed:
                    return candidate

        if self.OAUTH_ALLOWED_REDIRECT_URIS:
            return self.OAUTH_ALLOWED_REDIRECT_URIS[0]
        return self.GOOGLE_OAUTH_REDIRECT_URI


settings = Settings()
