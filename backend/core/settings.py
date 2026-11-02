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
        """Chuyển thành hằng số mức log của Python."""
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
    # Các khoá ký đã nghỉ vẫn được chấp nhận để xác minh trong lúc xoay khoá.
    JWT_PREVIOUS_SECRET_KEYS: list[SecretStr] = []
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "hercfit"
    JWT_AUDIENCE: str = "hercfit-api"
    JWT_LEEWAY_SECONDS: int = Field(default=10, ge=0, le=300)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Refresh token vừa bị thay gần đây có thể được gửi thêm một lần bởi
    # request đồng thời (nhiều tab song song hay lần thử lại) mà không thu hồi cả họ token.
    REFRESH_REUSE_GRACE_SECONDS: int = Field(default=30, ge=0, le=300)
    # None giữ mặc định lịch sử: cookie Secure ở mọi nơi trừ MODE=dev.
    COOKIE_SECURE: bool | None = None
    # Giới hạn theo client cho /api/auth/*; 0 để tắt bộ giới hạn.
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

    # Google Health API (kế nhiệm Google Fit REST API). Dùng lại OAuth client
    # của phần đăng nhập; callback được backend phục vụ qua origin của frontend.
    GOOGLE_HEALTH_ENABLED: bool = True
    GOOGLE_HEALTH_REDIRECT_URI: str | None = None
    GOOGLE_HEALTH_SYNC_LOOP: bool = True
    GOOGLE_HEALTH_SYNC_INTERVAL_MINUTES: int = Field(default=360, ge=15, le=7 * 24 * 60)
    # Gốc Google Health API. Chỉ ghi đè cho test hoặc emulator: https, hoặc http thường
    # trên localhost (access token của người dùng không bao giờ gửi qua http thường tới host khác).
    GOOGLE_HEALTH_API_ROOT: str = Field(
        default="https://health.googleapis.com",
        pattern=r"^(https://[A-Za-z0-9.-]+(:[0-9]+)?|http://(localhost|127\.0\.0\.1)(:[0-9]+)?)/?$")
    # Số request và độ trễ theo route (api_route_usage), ghi xuống mỗi phút một lần.
    API_ROUTE_METRICS: bool = True
    # Danh tính uỷ quyền cho service agent: nó chứng minh danh tính bằng HMAC trên mỗi
    # request uỷ quyền; sau đó backend cấp một token uỷ quyền ngắn hạn.
    AGENT_SERVICE_SECRET: SecretStr | None = None
    AGENT_SERVICE_PREVIOUS_SECRETS: list[SecretStr] = []
    AGENT_TOKEN_AUDIENCE: str = "hercfit-agent"
    AGENT_DELEGATION_MINUTES: int = Field(default=10, ge=1, le=60)
    # true: token người dùng có header tự khai báo X-HercFit-Client: agent bị từ chối.
    AGENT_DELEGATION_REQUIRED: bool = False
    # Khoá Fernet (base64 an toàn cho URL, 32 byte) cho token nhà cung cấp được lưu trữ. Khoá đầu
    # tiên dùng để mã hoá; các khoá trước vẫn giải mã được trong lúc xoay khoá.
    TOKEN_ENCRYPTION_KEY: SecretStr | None = None
    TOKEN_ENCRYPTION_PREVIOUS_KEYS: list[SecretStr] = []

    # Lưu trữ ảnh tuỳ chọn; secret chỉ được backend dùng.
    CLOUDINARY_CLOUD_NAME: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]+$")
    CLOUDINARY_API_KEY: SecretStr | None = None
    CLOUDINARY_API_SECRET: SecretStr | None = None
    CLOUDINARY_FOLDER: str = Field(default="hercfit", pattern=r"^[a-zA-Z0-9_-]+$")
    # Dùng chung với service agent, service này ký các lệnh finalize tra cứu bằng nó.
    # Thiếu nó thì /research-finalizations từ chối mọi lệnh (agentic/research/attestation.py).
    RESEARCH_ATTESTATION_SECRET: SecretStr | None = None
    RESEARCH_ATTESTATION_PREVIOUS_SECRETS: list[SecretStr] = []
    RESEARCH_ATTESTATION_MAX_AGE_HOURS: int = Field(default=24, ge=1, le=168)
    IMAGE_MAX_BYTES: int = Field(default=5 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    IMAGE_MAX_PIXELS: int = Field(default=20_000_000, ge=1, le=40_000_000)

    # Cấu hình PostgreSQL
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
        """Secret ký hiện tại đứng trước, rồi đến các secret đã nghỉ được giữ để xoay khoá."""
        return [self.jwt_secret_value, *(s.get_secret_value() for s in self.JWT_PREVIOUS_SECRET_KEYS if s.get_secret_value())]

    @property
    def cookie_secure(self) -> bool:
        return self.COOKIE_SECURE if self.COOKIE_SECURE is not None else not self.is_dev()

    @property
    def google_client_secret_value(self) -> str:
        if not self.GOOGLE_OAUTH_CLIENT_SECRET:
            raise ValueError("GOOGLE_OAUTH_CLIENT_SECRET is not configured in settings or .env")
        return self.GOOGLE_OAUTH_CLIENT_SECRET.get_secret_value()

    @property
    def google_health_redirect_uri(self) -> str:
        return self.GOOGLE_HEALTH_REDIRECT_URI or (
            f"{self.FRONTEND_URL.rstrip('/')}/api/integrations/google-health/callback")

    @property
    def agent_service_secrets(self) -> list[str]:
        secrets = [self.AGENT_SERVICE_SECRET, *self.AGENT_SERVICE_PREVIOUS_SECRETS]
        return [secret.get_secret_value() for secret in secrets if secret and secret.get_secret_value()]

    @property
    def google_health_configured(self) -> bool:
        return bool(self.GOOGLE_HEALTH_ENABLED and self.GOOGLE_OAUTH_CLIENT_ID
                    and self.GOOGLE_OAUTH_CLIENT_SECRET and self.TOKEN_ENCRYPTION_KEY)

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
