from agentic.core.paths import AGENTIC_ROOT, BACKEND_ROOT
from typing import Literal
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from agentic.core.app.env_sources import JevDotEnvSettingsSource, canonical_source

# Định nghĩa cấu hình cho Agentic Service
class AgentSettings(BaseSettings):
    # Agent-specific values override shared defaults, matching both Compose files.
    # Explicit process environment remains the highest-priority environment source.
    model_config = SettingsConfigDict(env_file=(str(BACKEND_ROOT / '.env'), str(AGENTIC_ROOT / '.env')), extra='ignore', env_ignore_empty=True)
    MODE: str = 'dev'
    AGENT_PORT: int = 8081
    BACKEND_BASE_URL: str = 'http://localhost:8080'
    BACKEND_TIMEOUT_SECONDS: float = 15
    DEFAULT_PROVIDER: Literal['fpt', 'openai', 'openai_compatible'] = 'fpt'
    DEFAULT_MODEL: str = 'DeepSeek-V4-Flash'
    DECISION_MODEL: str | None = None
    RESPONSE_MODEL: str | None = None
    TOOL_MODEL: str | None = None
    RESEARCH_MODEL: str | None = None
    MODEL_API_KEY: SecretStr | None = None
    OPENAI_API_KEY: SecretStr | None = None
    FPT_API_KEY: SecretStr | None = None
    FPT_BASE_URL: str = 'https://mkp-api.fptcloud.com'
    MODEL_BASE_URL: str = 'https://api.openai.com/v1'
    MODEL_TIMEOUT_SECONDS: float = 30
    # Per-role timeouts: routing/tool/clarify calls return small JSON and should
    # fail over quickly; a hung call previously cost 30 s twice (≈60 s tails).
    ROUTING_TIMEOUT_SECONDS: float = Field(default=12, gt=0)
    RESPONSE_TIMEOUT_SECONDS: float = Field(default=30, gt=0)
    RESEARCH_TIMEOUT_SECONDS: float = Field(default=45, gt=0)
    MODEL_MAX_RETRIES: int = Field(default=1, ge=0, le=3)
    CLARIFY_MODEL: str | None = None
    # Optional second OpenAI-compatible endpoint tried when the primary errors or times out.
    FALLBACK_PROVIDER: Literal['fpt', 'openai', 'openai_compatible'] | None = None
    FALLBACK_MODEL: str | None = None
    FALLBACK_BASE_URL: str | None = None
    FALLBACK_API_KEY: SecretStr | None = None
    # Stream answer tokens to the client (only the answer model streams; tool and
    # routing calls stay non-streaming so provider tool-call recovery keeps working).
    STREAM_RESPONSE_TOKENS: bool = True
    # Ask the provider for usage in streamed responses (stream_options.include_usage).
    MODEL_STREAM_USAGE: bool = False
    SSE_HEARTBEAT_SECONDS: float = Field(default=15, gt=0)
    TAVILY_API_KEY: SecretStr | None = None
    AGENT_DATABASE_URL: SecretStr = SecretStr('postgresql://hercfit:hercfit_secret@localhost:5432/hercfit_db')
    MAX_TOOL_CALLS: int = Field(default=12, ge=1, le=50)
    MAX_GRAPH_STEPS: int = Field(default=60, ge=10)
    RUN_TIMEOUT_SECONDS: float = Field(default=120, gt=0)
    CONFIRMATION_TTL_SECONDS: int = Field(default=1800, gt=0)
    RESEARCH_SOURCE_DOMAINS: list[str] = []
    # DeepSeek on FPT thinks ~9k tokens per extraction at default effort (25-70 s); "low" keeps
    # the same claims in 5-12 s. Applied to the FPT research client only (None disables).
    RESEARCH_REASONING_EFFORT: Literal['low', 'medium', 'high'] | None = 'low'
    # Shared with the backend (backend/.env): signs verified research finalization commands.
    RESEARCH_ATTESTATION_SECRET: SecretStr | None = None
    JEV_MODE: Literal['off', 'shadow', 'enforce'] = 'off'
    JEV_BASE_URL: str = Field(default='https://litellm.otanicloud.link/v1',
                              validation_alias=AliasChoices('JEV_BASE_URL', 'JEV_GATEWAY_URL'))
    JEV_API_KEY: SecretStr | None = None
    JEV_MODEL: str | None = None
    JEV_TIMEOUT_SECONDS: float = Field(default=3, gt=0, le=10)
    JEV_ENFORCE_PERCENT: int = Field(default=100, ge=0, le=100)
    JEV_POLICY_VERSION: str = Field(default='v1', min_length=1, max_length=64)
    JEV_INPUT_PRICE_PER_MILLION: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    JEV_OUTPUT_PRICE_PER_MILLION: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    RAG_ENABLED: bool = False
    LANGSMITH_ENABLED: bool = False
    KG_MODE: Literal['off', 'shadow', 'advisory', 'optimized'] = 'off'
    # Strict full-message templates for common reads (progress, current goal, latest
    # measurement, profile, calorie targets): one answer call instead of four.
    FAST_READ_ENABLED: bool = True
    NEO4J_URI: str = 'bolt://localhost:7687'
    NEO4J_USER: str = 'neo4j'
    NEO4J_PASSWORD: SecretStr | None = None
    NEO4J_DATABASE: str = 'neo4j'
    KG_BACKEND_DATABASE_URL: SecretStr | None = None
    KG_RETRIEVAL_TIMEOUT_MS: int = Field(default=150, ge=1, le=5000)
    KG_FACT_LIMIT: int = Field(default=12, ge=1, le=12)
    KG_EPISODE_LIMIT: int = Field(default=3, ge=0, le=3)
    KG_CONTEXT_TOKEN_BUDGET: int = Field(default=1500, ge=100, le=1500)
    KG_BUSINESS_RETENTION_DAYS: int = Field(default=90, ge=1)
    KG_MEMORY_RETENTION_DAYS: int = Field(default=30, ge=1)
    KG_WORKER_POLL_SECONDS: float = Field(default=1, gt=0)
    KG_WORKER_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)
    KG_RECONCILE_SECONDS: float = Field(default=5, gt=0)
    AGENT_DATABASE_POOL_SIZE: int = Field(default=10, ge=2)
    # Deprecated: sessions now use a timed lease row instead of a held advisory-lock connection.
    AGENT_SESSION_POOL_SIZE: int = Field(default=10, ge=1)
    # How long a second request for the same conversation waits before 409.
    SESSION_LEASE_WAIT_SECONDS: float = Field(default=30, ge=0, le=300)
    # Abuse and cost guards (OWASP LLM10). 0 disables a limit.
    AGENT_RATE_LIMIT_PER_MINUTE: int = Field(default=20, ge=0)
    AGENT_DAILY_TURN_LIMIT: int = Field(default=300, ge=0)
    AGENT_DAILY_TOKEN_LIMIT: int = Field(default=2_000_000, ge=0)
    # Verified identities are cached briefly to avoid one backend hop per request.
    IDENTITY_CACHE_SECONDS: float = Field(default=60, ge=0, le=600)
    # Run the checkpoint reconciler and memory purge in this process (disable on extra replicas).
    AGENT_BACKGROUND_TASKS: bool = True
    KG_RECONCILE_GRACE_SECONDS: float = Field(default=180, gt=0)
    CHECKPOINT_RETENTION_DAYS: int = Field(default=30, ge=1)
    # Redis session memory is an optional, rebuildable tier over checkpoints.
    # Promote off -> shadow -> on; any Redis failure falls back to checkpoints.
    REDIS_URL: SecretStr | None = None
    REDIS_KEY_PREFIX: str = Field(default='hf:agent', min_length=1, max_length=64)
    REDIS_TIMEOUT_MS: int = Field(default=100, ge=10, le=2000)
    SESSION_MEMORY_MODE: Literal['off', 'shadow', 'on'] = 'off'
    SESSION_MEMORY_TTL_SECONDS: int = Field(default=30 * 24 * 3600, gt=0)
    SESSION_MEMORY_MAX_TURNS: int = Field(default=200, ge=10, le=1000)
    # Verbatim messages carried into each turn; 40 matches the checkpoint-only behaviour.
    SESSION_MEMORY_WINDOW_MESSAGES: int = Field(default=40, ge=4, le=200)
    SESSION_MEMORY_SUMMARY_ENABLED: bool = True
    SESSION_MEMORY_SUMMARY_TRIGGER_TURNS: int = Field(default=4, ge=1, le=50)
    SESSION_MEMORY_SUMMARY_MAX_CHARS: int = Field(default=2000, ge=200, le=8000)
    SESSION_MEMORY_ENTITY_LIMIT: int = Field(default=20, ge=0, le=50)
    SUMMARY_MODEL: str | None = None
    CORS_ORIGINS: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173', 'http://localhost:5174', 'http://127.0.0.1:5174']

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        dotenv = JevDotEnvSettingsSource(
            settings_cls, env_file=dotenv_settings.env_file,
            env_file_encoding=dotenv_settings.env_file_encoding,
            case_sensitive=dotenv_settings.case_sensitive,
            env_ignore_empty=dotenv_settings.env_ignore_empty,
        )
        return tuple(canonical_source(source) for source in (init_settings, env_settings, dotenv, file_secret_settings))

    def check(self):
        if self.JEV_MODE != 'off':
            self.check_jev()
        if not self.model_api_key:
            raise ValueError(f'API key for {self.DEFAULT_PROVIDER} is required; runtime never falls back to fake models')
        if not self.TAVILY_API_KEY and self.MODE != 'dev':
            raise ValueError('TAVILY_API_KEY is required')
        if self.SESSION_MEMORY_MODE != 'off' and not self.REDIS_URL:
            raise ValueError('REDIS_URL is required when SESSION_MEMORY_MODE is enabled')

    def check_jev(self, *, require_model=True):
        from urllib.parse import urlsplit
        url = urlsplit(self.JEV_BASE_URL)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('JEV_BASE_URL / JEV_GATEWAY_URL must be an HTTPS API base without credentials, query or fragment')
        if require_model and (not self.JEV_MODEL or not self.JEV_MODEL.strip()):
            raise ValueError('JEV_MODEL is required; discover the gateway model using agentic.scripts.jev_preflight')
        if not self.JEV_API_KEY or not self.JEV_API_KEY.get_secret_value().strip():
            raise ValueError('JEV_API_KEY (gateway virtual key) is required when Jev is enabled')

    @property
    def model_api_key(self):
        if self.DEFAULT_PROVIDER == 'fpt':
            return self.FPT_API_KEY
        return self.MODEL_API_KEY or self.OPENAI_API_KEY

    @property
    def model_base_url(self):
        return self.FPT_BASE_URL if self.DEFAULT_PROVIDER == 'fpt' else self.MODEL_BASE_URL

    @property
    def session_lease_seconds(self):
        # Covers the whole run plus journaling; an abandoned lease simply expires.
        return self.RUN_TIMEOUT_SECONDS + 60

agent_settings = AgentSettings()
