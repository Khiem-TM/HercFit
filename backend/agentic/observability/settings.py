"""Cấu hình tường minh dùng chung cho API và worker; không bao giờ tự bật thu thập của SDK."""

import hashlib
import hmac
from pathlib import Path
from typing import Literal

from pydantic import Field, PrivateAttr, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).parents[2]


class ObservabilitySettings(BaseSettings):
    # Thứ tự ưu tiên: biến môi trường tiến trình → backend/.env → backend/agentic/.env.
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND / "agentic/.env"), str(BACKEND / ".env")),
        extra="ignore",
        env_ignore_empty=True,
    )
    LANGFUSE_TRACING: bool = False
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: SecretStr | None = None
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"
    LANGFUSE_TRACING_ENVIRONMENT: str = "dev"
    # Release gắn vào mọi trace và lần chạy eval. Chưa đặt thì lấy commit từ HERCFIT_RELEASE/GIT_COMMIT_SHA
    # (Dockerfile và dev_up.sh truyền vào); vẫn thiếu thì "unknown" và /health/ready báo release_configured=false.
    LANGFUSE_RELEASE: str = "unknown"
    HERCFIT_RELEASE: str | None = None
    GIT_COMMIT_SHA: str | None = None
    # Mức log của ứng dụng (dùng chung tên với backend) và của log hoàn tất request/kết cục chat. Log request
    # có mức riêng để vẫn ghi được khi mức chung là WARNING: đó là log tương quan request_id ↔ trace_id.
    LOG_LEVEL: str = "WARNING"
    REQUEST_LOG_LEVEL: str = "INFO"
    LANGFUSE_CAPTURE_MODE: Literal["redacted", "metadata_only"] = "redacted"
    LANGFUSE_SAMPLE_RATE: float = Field(default=1, ge=0, le=1)
    LANGFUSE_PSEUDONYM_SECRET: SecretStr | None = None
    LANGFUSE_PROPAGATION_SECRET: SecretStr | None = None
    LANGFUSE_FLUSH_SECONDS: float = Field(default=3, gt=0, le=30)
    # Giá đã kiểm chứng cho đo chi phí cục bộ, ví dụ
    # {"fpt/DeepSeek-V4-Flash": {"input_per_million": 0.0, "output_per_million": 0.0}}
    MODEL_PRICES: dict[str, dict[str, float]] = Field(default_factory=dict)

    # 'explicit' khi đặt trong biến môi trường, 'derived' khi tính từ secret key.
    _secret_sources: dict = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def derive_missing_secrets(self):
        """Secret bí danh và lan truyền là tuỳ chọn.

        Khi chưa đặt, chúng được suy ra từ LANGFUSE_SECRET_KEY bằng HMAC-SHA256 với một
        nhãn riêng cho từng mục đích, nên ID người dùng/phiên vẫn được đặt bí danh và header trace
        service-tới-service vẫn được ký. Mọi service đọc cùng secret key đều suy ra cùng
        giá trị. Xoay key sẽ đổi bí danh; đặt biến tường minh để tránh điều đó.
        """
        key = self.LANGFUSE_SECRET_KEY.get_secret_value() if self.LANGFUSE_SECRET_KEY else ""
        sources = {}
        for name, label in (
            ("LANGFUSE_PSEUDONYM_SECRET", b"hercfit/langfuse/pseudonym/v1"),
            ("LANGFUSE_PROPAGATION_SECRET", b"hercfit/langfuse/propagation/v1"),
        ):
            if getattr(self, name):
                sources[name] = "explicit"
            elif key:
                setattr(
                    self, name, SecretStr(hmac.new(key.encode(), label, hashlib.sha256).hexdigest())
                )
                sources[name] = "derived"
        self._secret_sources = sources
        return self

    @model_validator(mode="after")
    def derive_release(self):
        if self.LANGFUSE_RELEASE in ("", "unknown"):
            self.LANGFUSE_RELEASE = self.HERCFIT_RELEASE or self.GIT_COMMIT_SHA or "unknown"
        return self

    @property
    def release_configured(self):
        return self.LANGFUSE_RELEASE != "unknown"

    @property
    def secret_sources(self):
        return dict(self._secret_sources)

    @property
    def enabled(self):
        return self.LANGFUSE_TRACING

    @property
    def configured(self):
        return bool(
            self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY and self.LANGFUSE_PSEUDONYM_SECRET
        )
