"""Phần dùng chung cho nạp và truy hồi RAG: cấu hình + profile, client embedding/rerank, chuẩn hoá văn bản."""

import math
import re
import unicodedata
from collections import OrderedDict
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from time import monotonic

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentic.observability import annotate, observed

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Cache vector truy vấn theo văn bản chính xác (không phải cache ngữ nghĩa): câu hỏi lặp lại hoặc thử lại bỏ qua
# lượt gọi nhà cung cấp. Các đoạn văn được worker tiếp nhận embed một lần và không bao giờ được cache.
QUERY_CACHE_SIZE = 512
QUERY_CACHE_SECONDS = 3600
E5_MODEL = "multilingual-e5-large"


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"), extra="ignore", env_ignore_empty=True
    )

    RAG_ENABLED: bool = False
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_MODEL: str = ""
    EMBEDDING_DIMENSION: int = Field(default=0, ge=0)
    EMBEDDING_API_KEY: SecretStr | None = None
    EMBEDDING_REVISION: str = "1"
    EMBEDDING_TIMEOUT_SECONDS: float = Field(default=15, gt=0)
    # Xếp hạng lại bằng cross-encoder trên cùng nhà cung cấp và khoá (FPT: bge-reranker-v2-m3 tại /v1/rerank).
    RERANK_ENABLED: bool = False
    RERANK_MODEL: str = "bge-reranker-v2-m3"
    RERANK_PATH: str = "v1/rerank"
    RERANK_TIMEOUT_SECONDS: float = Field(default=5, gt=0, le=30)
    # Số ứng viên đã hợp nhất gửi cho reranker, và độ sâu của mỗi danh sách dense/từ khoá.
    RAG_CANDIDATES: int = Field(default=24, ge=1, le=64)
    # Số chunk giữ lại cho mỗi trang nguồn, để các cửa sổ chồng nhau của một trang không chèn ép bằng chứng khác.
    RAG_MAX_PER_PAGE: int = Field(default=1, ge=1, le=10)
    # Dưới các ngưỡng này, cơ sở tri thức được coi là không bao quát câu hỏi (hiệu chỉnh bằng
    # agentic.evaluation.rag_eval); điểm rerank áp dụng khi rerank thành công, nếu không thì dùng cosine.
    RAG_MIN_RERANK_SCORE: float | None = Field(default=None, ge=0, le=1)
    RAG_MIN_DENSE_SIMILARITY: float | None = Field(default=None, ge=-1, le=1)

    def check_embedding(self):
        if not self.EMBEDDING_BASE_URL or not self.EMBEDDING_MODEL or not self.EMBEDDING_DIMENSION:
            raise ValueError(
                "Configure EMBEDDING_BASE_URL, EMBEDDING_MODEL and EMBEDDING_DIMENSION"
            )

    @property
    def profile_id(self):
        """Định danh không gian vector; vector của hai profile khác nhau không bao giờ được so sánh."""
        key = f"{self.EMBEDDING_BASE_URL}|{self.EMBEDDING_MODEL}|{self.EMBEDDING_REVISION}|{self.EMBEDDING_DIMENSION}"
        return sha256(key.encode()).hexdigest()


@lru_cache
def settings():
    return EmbeddingSettings()


def normalize_text(value):
    """Chữ thường, bỏ dấu tiếng Việt và gộp khoảng trắng, cho cả search_vector lúc nạp và câu truy vấn.

    Đây là hợp đồng với các tsvector đã lưu: đổi cách chuẩn hoá thì phải nạp lại mọi revision.
    """
    value = unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
    return " ".join("".join(char for char in value if not unicodedata.combining(char)).split())


# Từ tiếng Việt viết không dấu thường gặp trong câu hỏi; chỉ giữ từ không trùng với từ tiếng Anh hay gặp
# ("the", "an", "can", "de" bị loại vì "the de Castella", "how can I"...).
VIETNAMESE_WORDS = frozenset(
    "khong nhu nao cua voi nguoi gi bao nhieu nen sao lam duoc khi chay uong truoc trong "
    "moi ngay tuan hon nhanh toi minh cho va co la tap sau giam".split()
)


def is_english(text):
    """Truy vấn tiếng Anh cho kho sách tiếng Anh: chỉ ký tự ASCII và không có từ tiếng Việt không dấu nào.

    isascii() thôi chưa đủ: "lam sao chay 5k nhanh hon" cũng là ASCII.
    """
    return text.isascii() and VIETNAMESE_WORDS.isdisjoint(re.findall(r"[a-z]+", text.lower()))


def record_usage(model, provider, tokens):
    """Gắn model và số token (khi nhà cung cấp trả về) vào span đang mở; giá chưa biết."""
    annotate(hercfit_model=model, hercfit_provider=provider, cost_status="unknown")
    if type(tokens) is int and tokens >= 0:
        annotate(
            usage_metadata={"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens}
        )


class ProviderClient:
    """Kết nối tới nhà cung cấp kiểu OpenAI; embedding và rerank dùng chung endpoint và khoá."""

    def __init__(self, settings, timeout, transport=None):
        settings.check_embedding()
        self.settings = settings
        key = settings.EMBEDDING_API_KEY
        self.http = httpx.AsyncClient(
            base_url=settings.EMBEDDING_BASE_URL.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + key.get_secret_value()} if key else {},
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    async def close(self):
        await self.http.aclose()


class EmbeddingClient(ProviderClient):
    def __init__(self, settings, transport=None):
        super().__init__(settings, settings.EMBEDDING_TIMEOUT_SECONDS, transport)
        self.cache = OrderedDict()

    async def embed(self, texts, *, input_type="query"):
        if not texts or len(texts) > 32:
            raise ValueError("Embedding batch must contain 1..32 texts")
        if input_type not in {"query", "passage"}:
            raise ValueError("input_type must be query or passage")
        if input_type != "query":
            return await self.request(texts, input_type)
        now = monotonic()
        for text in [t for t, (at, _) in self.cache.items() if now - at > QUERY_CACHE_SECONDS]:
            del self.cache[text]
        missing = [t for t in dict.fromkeys(texts) if t not in self.cache]
        if missing:
            for text, vector in zip(missing, await self.request(missing, input_type)):
                self.cache[text] = (now, vector)
        for text in texts:
            self.cache.move_to_end(text)
        vectors = [list(self.cache[t][1]) for t in texts]
        while len(self.cache) > QUERY_CACHE_SIZE:
            self.cache.popitem(last=False)
        return vectors

    @observed("embedding.request", "embedding", capture=("texts",), output=False)
    async def request(self, texts, input_type):
        model = self.settings.EMBEDDING_MODEL
        # Truy hồi E5 cần tiền tố bất đối xứng, kể cả với đầu vào không phải tiếng Anh.
        if model.rsplit("/", 1)[-1] == E5_MODEL:
            prefix = input_type + ": "
            texts = [prefix + text.removeprefix(prefix) for text in texts]
        annotate(model=model, input_count=len(texts))
        response = await self.http.post("embeddings", json={"model": model, "input": texts})
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        record_usage(model, "embedding", usage.get("prompt_tokens", usage.get("total_tokens")))
        rows = sorted(data["data"], key=lambda r: r["index"])
        if [r["index"] for r in rows] != list(range(len(texts))):
            raise ValueError("Embedding response indices mismatch")
        vectors = [r["embedding"] for r in rows]
        for vector in vectors:
            if (
                len(vector) != self.settings.EMBEDDING_DIMENSION
                or not any(vector)
                or not all(type(n) in (int, float) and math.isfinite(n) for n in vector)
            ):
                raise ValueError("Invalid embedding vector/dimension")
        return vectors


class RerankClient(ProviderClient):
    """Điểm liên quan của cross-encoder từ endpoint /rerank kiểu OpenAI."""

    def __init__(self, settings, transport=None):
        super().__init__(settings, settings.RERANK_TIMEOUT_SECONDS, transport)

    @observed("rerank.request", "reranker", capture=("query",), output=False)
    async def rerank(self, query, documents):
        """Mỗi tài liệu một điểm, theo thứ tự đầu vào."""
        if not documents or len(documents) > 64:
            raise ValueError("Rerank batch must contain 1..64 documents")
        model = self.settings.RERANK_MODEL
        annotate(model=model, input_count=len(documents))
        response = await self.http.post(
            self.settings.RERANK_PATH,
            json={"model": model, "query": query, "documents": documents, "top_n": len(documents)},
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise ValueError("Unexpected rerank response")
        scores = {}
        for item in results:
            index = item.get("index") if isinstance(item, dict) else None
            score = item.get("relevance_score") if isinstance(item, dict) else None
            if (
                type(index) is not int
                or not 0 <= index < len(documents)
                or index in scores
                or type(score) not in (int, float)
                or not math.isfinite(score)
            ):
                raise ValueError("Invalid rerank result")
            scores[index] = float(score)
        if len(scores) != len(documents):
            raise ValueError("Incomplete rerank result")
        record_usage(model, "rerank", (data.get("usage") or {}).get("total_tokens"))
        return [scores[i] for i in range(len(documents))]
