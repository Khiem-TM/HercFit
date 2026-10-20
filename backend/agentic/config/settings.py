"""Environment variables, LLM provider keys, Backend URLs, and YAML configuration loader."""

from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import BeforeValidator, HttpUrl, SecretStr, TypeAdapter
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parent
AGENTIC_ROOT = CONFIG_DIR.parent
DEFAULT_YAML_PATH = CONFIG_DIR / "agent_config.yaml"


class CheckpointBackend(StrEnum):
    MEMORY = "memory"
    POSTGRES = "postgres"
    REDIS = "redis"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    def to_logging_level(self) -> int:
        import logging

        return getattr(logging, self.value, logging.INFO)


def _validate_http_url(value: str) -> str:
    adapter = TypeAdapter(HttpUrl)
    return str(adapter.validate_python(value)).rstrip("/")


class AgentSettings(BaseSettings):
    """Centralized settings for the Agentic microservice, including all LLM & Agent configs."""

    model_config = SettingsConfigDict(
        env_file=(str(AGENTIC_ROOT / ".env"), str(AGENTIC_ROOT.parent / ".env")),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        validate_default=False,
    )

    # --- Service Runtime ---
    MODE: str = "dev"
    AGENT_HOST: str = "0.0.0.0"
    AGENT_PORT: int = 8081
    LOG_LEVEL: LogLevel = LogLevel.INFO
    GRACEFUL_SHUTDOWN_TIMEOUT: int = 30
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:8501",
    ]

    # --- Security & Authentication ---
    AUTH_SECRET: SecretStr | None = None
    JWT_SECRET_KEY: SecretStr | None = None
    JWT_SECRET: SecretStr | None = None
    JWT_ALGORITHM: str = "HS256"

    # --- Internal CRUD Backend Connection ---
    BACKEND_BASE_URL: Annotated[str, BeforeValidator(_validate_http_url)] = (
        "http://localhost:8080"
    )
    BACKEND_TIMEOUT_SECONDS: float = 15.0
    BACKEND_MAX_RETRIES: int = 3

    # --- LLM Providers & Model Settings ---
    DEFAULT_PROVIDER: str = "openai"
    DEFAULT_MODEL: str = "gpt-5-nano"
    AVAILABLE_MODELS: set[str] = {
        "gpt-5-nano",
        "gpt-5-mini",
        "gpt-5.1",
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "ollama",
        "fake",
    }
    USE_FAKE_MODEL: bool = True

    MODEL_API_KEY: SecretStr | None = None
    MODEL_BASE_URL: str = "https://api.openai.com/v1"
    MODEL_TIMEOUT_SECONDS: float = 30.0
    MODEL_MAX_RETRIES: int = 2
    MODEL_TEMPERATURE: float = 0.2

    OPENAI_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None
    GOOGLE_API_KEY: SecretStr | None = None
    OPENROUTER_API_KEY: SecretStr | None = None
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"

    COMPATIBLE_MODEL: str | None = None
    COMPATIBLE_API_KEY: SecretStr | None = None
    COMPATIBLE_BASE_URL: str | None = None

    # --- Embeddings & Long-Term Memory (RAG / pgvector) ---
    EMBEDDING_MODEL: str | None = None
    EMBEDDING_DIMENSIONS: int = 1536
    PGVECTOR_ENABLED: bool = True
    SHORT_TERM_MAX_MESSAGES: int = 20

    # --- Checkpoints & Persistence (Memory / Postgres / Redis) ---
    CHECKPOINT_BACKEND: CheckpointBackend = CheckpointBackend.MEMORY
    SQLITE_DB_PATH: str = "checkpoints.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    POSTGRES_USER: str = "hercfit"
    POSTGRES_PASSWORD: SecretStr = SecretStr("hercfit_secret")
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "hercfit_db"
    POSTGRES_APPLICATION_NAME: str = "hercfit-agentic"
    POSTGRES_MIN_CONNECTIONS_PER_POOL: int = 1
    POSTGRES_MAX_CONNECTIONS_PER_POOL: int = 5
    POSTGRES_POOL_TIMEOUT: float = 30.0
    POSTGRES_CONNECT_TIMEOUT: float = 10.0

    # --- Observability & Tracing (LangSmith / Langfuse) ---
    LANGSMITH_TRACING: bool = False
    LANGSMITH_PROJECT: str = "hercfit-agentic"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGSMITH_API_KEY: SecretStr | None = None

    LANGFUSE_TRACING: bool = False
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_PUBLIC_KEY: SecretStr | None = None
    LANGFUSE_SECRET_KEY: SecretStr | None = None

    @property
    def effective_api_key(self) -> SecretStr | None:
        return (
            self.MODEL_API_KEY
            or self.OPENAI_API_KEY
            or self.OPENROUTER_API_KEY
            or self.ANTHROPIC_API_KEY
            or self.GOOGLE_API_KEY
            or self.COMPATIBLE_API_KEY
        )

    @property
    def jwt_secret_value(self) -> str | None:
        secret = self.JWT_SECRET_KEY or self.JWT_SECRET or self.AUTH_SECRET
        return secret.get_secret_value() if secret else None

    def is_dev(self) -> bool:
        return self.MODE.lower() in {"dev", "development", "local", "test"}

    def validate_agent_configuration(self) -> None:
        """Ensure an LLM API key is configured when running in production without fake model."""
        if self.USE_FAKE_MODEL or self.is_dev():
            return
        if not self.effective_api_key:
            raise ValueError(
                "At least one LLM API key (MODEL_API_KEY, OPENAI_API_KEY, etc.) must be set in prod mode."
            )


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Fallback parser if PyYAML is not installed, supporting standard nested dicts and multiline strings."""
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass

    result: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        raw_line = lines[idx]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            idx += 1
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current_dict = stack[-1][1]
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val in {"|", ">"}:
                block_lines: list[str] = []
                idx += 1
                while idx < len(lines):
                    next_raw = lines[idx]
                    next_strip = next_raw.strip()
                    next_indent = len(next_raw) - len(next_raw.lstrip(" "))
                    if next_strip and next_indent <= indent:
                        break
                    block_lines.append(next_strip)
                    idx += 1
                current_dict[key] = "\n".join(block_lines).strip()
                continue
            elif val == "":
                new_section: dict[str, Any] = {}
                current_dict[key] = new_section
                stack.append((indent, new_section))
            else:
                val_clean = val.strip("\"'")
                if val_clean.lower() in {"true", "false"}:
                    current_dict[key] = val_clean.lower() == "true"
                else:
                    try:
                        current_dict[key] = (
                            float(val_clean) if "." in val_clean else int(val_clean)
                        )
                    except ValueError:
                        current_dict[key] = val_clean
        idx += 1
    return result


@cache
def load_agent_yaml_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load and cache agent parameters, prompts, and timeouts from agent_config.yaml."""
    path = Path(config_path) if config_path else DEFAULT_YAML_PATH
    if not path.exists():
        return {}
    return _parse_simple_yaml(path.read_text(encoding="utf-8"))


agent_settings = AgentSettings()

