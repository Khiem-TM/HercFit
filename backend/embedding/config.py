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
    # Xếp hạng lại bằng cross-encoder trên cùng nhà cung cấp và khoá (FPT: bge-reranker-v2-m3 tại /v1/rerank).
    RERANK_ENABLED: bool=False
    RERANK_MODEL: str='bge-reranker-v2-m3'
    RERANK_PATH: str='v1/rerank'
    RERANK_TIMEOUT_SECONDS: float=Field(default=5,gt=0,le=30)
    # Số ứng viên đã hợp nhất gửi cho reranker, và độ sâu của mỗi danh sách dense/từ khoá.
    RAG_CANDIDATES: int=Field(default=24,ge=1,le=64)
    # Số chunk giữ lại cho mỗi trang nguồn, để các cửa sổ chồng nhau của một trang không chèn ép bằng chứng khác.
    RAG_MAX_PER_PAGE: int=Field(default=1,ge=1,le=10)
    # Dưới các ngưỡng này, cơ sở tri thức được coi là không bao quát câu hỏi (hiệu chỉnh bằng
    # agentic.evaluation.rag_eval); điểm rerank áp dụng khi rerank thành công, nếu không thì dùng cosine.
    RAG_MIN_RERANK_SCORE: float | None=Field(default=None,ge=0,le=1)
    RAG_MIN_DENSE_SIMILARITY: float | None=Field(default=None,ge=-1,le=1)

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
