from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(str(Path(__file__).parents[2] / '.env'), str(Path(__file__).parents[1] / '.env')), extra='ignore', env_ignore_empty=True)
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
    TAVILY_API_KEY: SecretStr | None = None
    AGENT_DATABASE_URL: SecretStr = SecretStr('postgresql://hercfit:hercfit_secret@localhost:5432/hercfit_db')
    MAX_TOOL_CALLS: int = Field(default=12, ge=1, le=50)
    MAX_GRAPH_STEPS: int = Field(default=60, ge=10)
    RUN_TIMEOUT_SECONDS: float = Field(default=120, gt=0)
    CONFIRMATION_TTL_SECONDS: int = Field(default=1800, gt=0)
    KG_MODE: Literal['off', 'shadow', 'advisory', 'optimized'] = 'off'
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
    # Session advisory locks must not consume checkpoint/store connections.
    AGENT_DATABASE_POOL_SIZE: int = Field(default=10, ge=2)
    AGENT_SESSION_POOL_SIZE: int = Field(default=10, ge=1)
    CORS_ORIGINS: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173', 'http://localhost:5174', 'http://127.0.0.1:5174']

    def check(self):
        if not self.model_api_key:
            raise ValueError(f'API key for {self.DEFAULT_PROVIDER} is required; runtime never falls back to fake models')
        if not self.TAVILY_API_KEY and self.MODE != 'dev':
            raise ValueError('TAVILY_API_KEY is required')

    @property
    def model_api_key(self):
        if self.DEFAULT_PROVIDER == 'fpt':
            return self.FPT_API_KEY
        return self.MODEL_API_KEY or self.OPENAI_API_KEY

    @property
    def model_base_url(self):
        return self.FPT_BASE_URL if self.DEFAULT_PROVIDER == 'fpt' else self.MODEL_BASE_URL

agent_settings = AgentSettings()
