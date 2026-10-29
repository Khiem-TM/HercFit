from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class EmbeddingSettings(BaseSettings):
    model_config=SettingsConfigDict(env_file=str(Path(__file__).parents[1]/'.env'),extra='ignore',env_ignore_empty=True)
    RAG_ENABLED: bool=False
    EMBEDDING_BASE_URL: str=''
    EMBEDDING_MODEL: str=''
    EMBEDDING_DIMENSION: int=Field(default=0,ge=0)
    EMBEDDING_API_KEY: SecretStr | None=None
    EMBEDDING_REVISION: str='1'
    EMBEDDING_TIMEOUT_SECONDS: float=Field(default=15,gt=0)
    KNOWLEDGE_INGEST_ROOT: str='knowledge-input'
    KNOWLEDGE_MAX_FILE_BYTES: int=20_000_000
    KNOWLEDGE_WORKER_POLL_SECONDS: float=2

    def check_embedding(self):
        if not self.EMBEDDING_BASE_URL or not self.EMBEDDING_MODEL or not self.EMBEDDING_DIMENSION:
            raise ValueError('Configure EMBEDDING_BASE_URL, EMBEDDING_MODEL and EMBEDDING_DIMENSION')

    @property
    def profile_id(self):
        from hashlib import sha256
        return sha256(f'{self.EMBEDDING_BASE_URL}|{self.EMBEDDING_MODEL}|{self.EMBEDDING_REVISION}|{self.EMBEDDING_DIMENSION}'.encode()).hexdigest()

@lru_cache
def settings():
    return EmbeddingSettings()
