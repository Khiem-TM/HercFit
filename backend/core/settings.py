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
    # Retired signing keys still accepted for verification during a key rotation.
    JWT_PREVIOUS_SECRET_KEYS: list[SecretStr] = []
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "hercfit"
    JWT_AUDIENCE: str = "hercfit-api"
    JWT_LEEWAY_SECONDS: int = Field(default=10, ge=0, le=300)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # A refresh token replaced this recently may be presented once more by a
    # concurrent request (parallel tabs or retries) without revoking the family.
    REFRESH_REUSE_GRACE_SECONDS: int = Field(default=30, ge=0, le=300)
    # None keeps the historical default: Secure cookies everywhere except MODE=dev.
    COOKIE_SECURE: bool | None = None
    # Per-client limit for /api/auth/*; 0 disables the limiter.
    AUTH_RATE_LIMIT_PER_MINUTE: int = Field(default=30, ge=0)

    # Google OAuth
    GOOGLE_OAUTH_CLIENT_ID: str | None = None
    GOOGLE_OAUTH_CLIENT_SECRET: SecretStr | None = None
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:5173/auth/callback"
    OAUTH_ALLOWED_REDIRECT_URIS: list[str] = [
        "http://localhost:5173/auth/callback",
        "http://localhost:5174/auth/callback",
    ]
    FRONTEND_URL: str = "http://localhost:5173"

    # Optional image storage; secrets are used only by the backend.
    CLOUDINARY_CLOUD_NAME: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]+$")
    CLOUDINARY_API_KEY: SecretStr | None = None
    CLOUDINARY_API_SECRET: SecretStr | None = None
    CLOUDINARY_FOLDER: str = Field(default="hercfit", pattern=r"^[a-zA-Z0-9_-]+$")
    # Shared with the agent service, which signs research finalization commands with it.
    # Without it /research-finalizations refuses every command (research/attestation.py).
    RESEARCH_ATTESTATION_SECRET: SecretStr | None = None
    RESEARCH_ATTESTATION_PREVIOUS_SECRETS: list[SecretStr] = []
    RESEARCH_ATTESTATION_MAX_AGE_HOURS: int = Field(default=24, ge=1, le=168)
    IMAGE_MAX_BYTES: int = Field(default=5 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    IMAGE_MAX_PIXELS: int = Field(default=20_000_000, ge=1, le=40_000_000)

    # PostgreSQL Configuration
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: SecretStr | None = None
    POSTGRES_HOST: str | None = None
    POSTGRES_PORT: int | None = None
    POSTGRES_DB: str | None = None
    POSTGRES_APPLICATION_NAME: str = "hercfit-backend"
    POSTGRES_MIN_CONNECTIONS_PER_POOL: int = 2
    POSTGRES_MAX_CONNECTIONS_PER_POOL: int = 10
    POSTGRES_POOL_TIMEOUT: float = 30.0
    POSTGRES_CONNECT_TIMEOUT: float = 10.0

    @property
    def jwt_secret_value(self) -> str:
        secret = self.JWT_SECRET_KEY or self.JWT_SECRET or self.AUTH_SECRET
        if not secret:
            raise ValueError("JWT secret is not configured in settings or .env")
        return secret.get_secret_value()

    @property
    def jwt_verification_secrets(self) -> list[str]:
        """Current signing secret first, then retired secrets kept for rotation."""
        return [self.jwt_secret_value, *(s.get_secret_value() for s in self.JWT_PREVIOUS_SECRET_KEYS if s.get_secret_value())]

    @property
    def cookie_secure(self) -> bool:
        return self.COOKIE_SECURE if self.COOKIE_SECURE is not None else not self.is_dev()

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
