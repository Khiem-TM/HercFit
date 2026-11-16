"""Thiết lập tiếp nhận; secret lấy từ biến môi trường hoặc các file .env bị bỏ qua khỏi Git."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from agentic.embedding.core import BACKEND_ROOT, EmbeddingSettings

INGESTION_ROOT = Path(__file__).resolve().parent
# Sách nguồn, gói đã chuẩn bị và cache tokenizer không bao giờ được đưa vào quản lý phiên bản.
DATA_ROOT = INGESTION_ROOT / "data"


class IngestionSettings(EmbeddingSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(BACKEND_ROOT / ".env"),
            str(BACKEND_ROOT / "agentic/.env"),
            str(INGESTION_ROOT / ".env"),
        ),
        extra="ignore",
        env_ignore_empty=True,
    )
    EMBEDDING_TIMEOUT_SECONDS: float = Field(default=30, gt=0, le=45)
    KNOWLEDGE_INGEST_ROOT: str = str(DATA_ROOT / "input")
    KNOWLEDGE_MAX_FILE_BYTES: int = 20_000_000
    KNOWLEDGE_MAX_EXTRACTED_CHARS: int = 10_000_000
    KNOWLEDGE_WORKER_POLL_SECONDS: float = 2
    KNOWLEDGE_EMBEDDING_BATCH_SIZE: int = Field(default=8, ge=1, le=32)
    KNOWLEDGE_EMBEDDING_RETRIES: int = Field(default=3, ge=1, le=6)
    KNOWLEDGE_REQUEST_INTERVAL: float = Field(default=0.2, ge=0)
    KNOWLEDGE_TOKENIZER_PATH: str = str(DATA_ROOT / ".cache/e5-tokenizer.json")



@lru_cache
def settings():
    return IngestionSettings()
