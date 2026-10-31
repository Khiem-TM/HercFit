"""Explicit configuration shared by APIs and workers; never auto-enable SDK capture."""
import hashlib
import hmac
from pathlib import Path
from typing import Literal
from pydantic import Field, PrivateAttr, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(str(Path(__file__).parents[1] / 'agentic/.env'), str(Path(__file__).parents[1] / '.env')), extra='ignore', env_ignore_empty=True)
    MODE: str | None = None
    LANGSMITH_TRACING: bool | None = None
    LANGSMITH_ENABLED: bool = False
    LANGSMITH_API_KEY: SecretStr | None = None
    LANGSMITH_ENDPOINT: str = 'https://api.smith.langchain.com'
    LANGSMITH_WORKSPACE_ID: str | None = None
    LANGSMITH_PROJECT: str | None = None
    LANGSMITH_ENVIRONMENT: str = 'dev'
    LANGSMITH_REVISION: str = 'unknown'
    LANGSMITH_CAPTURE_MODE: Literal['redacted', 'metadata_only'] = 'redacted'
    LANGSMITH_TRACING_SAMPLING_RATE: float = Field(default=1, ge=0, le=1)
    LANGSMITH_PSEUDONYM_SECRET: SecretStr | None = None
    LANGSMITH_PROPAGATION_SECRET: SecretStr | None = None
    LANGSMITH_BUFFER_SIZE: int = Field(default=1000, ge=10, le=100000)
    LANGSMITH_FLUSH_SECONDS: float = Field(default=3, gt=0, le=30)
    # {"fpt/DeepSeek-V4-Flash": {"input_per_million": 0.0, "output_per_million": 0.0}}
    LANGSMITH_MODEL_PRICES: dict[str, dict[str, float]] = Field(default_factory=dict)
    LANGSMITH_ALERT_WEBHOOK_URL: SecretStr | None = None
    LANGSMITH_COST_ALERT_USD: float | None = Field(default=None, gt=0)

    # 'explicit' when set in the environment, 'derived' when computed from the API key.
    _secret_sources: dict = PrivateAttr(default_factory=dict)

    @model_validator(mode='after')
    def derive_missing_secrets(self):
        """Pseudonym and propagation secrets are optional.

        When unset they are derived from LANGSMITH_API_KEY with HMAC-SHA256 and a distinct
        label per purpose, so user/session IDs are still pseudonymised and service-to-service
        trace headers are still signed. Every service reading the same API key derives the same
        values. Rotating the API key changes pseudonyms; set the variables explicitly to avoid that.
        """
        key = self.LANGSMITH_API_KEY.get_secret_value() if self.LANGSMITH_API_KEY else ''
        sources = {}
        for name, label in (('LANGSMITH_PSEUDONYM_SECRET', b'hercfit/langsmith/pseudonym/v1'),
                            ('LANGSMITH_PROPAGATION_SECRET', b'hercfit/langsmith/propagation/v1')):
            if getattr(self, name):
                sources[name] = 'explicit'
            elif key:
                setattr(self, name, SecretStr(hmac.new(key.encode(), label, hashlib.sha256).hexdigest()))
                sources[name] = 'derived'
        self._secret_sources = sources
        return self

    @property
    def secret_sources(self):
        return dict(self._secret_sources)

    @property
    def enabled(self):
        return self.MODE == 'dev' and (self.LANGSMITH_TRACING if self.LANGSMITH_TRACING is not None else self.LANGSMITH_ENABLED)

    @property
    def project(self):
        return self.LANGSMITH_PROJECT or ('hercfit-agentic-prod' if self.LANGSMITH_ENVIRONMENT == 'prod' else 'hercfit-agentic')

    @property
    def configured(self):
        return bool(self.LANGSMITH_API_KEY and self.LANGSMITH_PSEUDONYM_SECRET)
