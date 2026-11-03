import math

from agentic.embedding.core.provider import provider_http, record_usage
from agentic.observability import annotate, observed


class RerankClient:
    """Điểm liên quan của cross-encoder từ endpoint /rerank kiểu OpenAI."""

    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = provider_http(settings, settings.RERANK_TIMEOUT_SECONDS, transport)

    async def close(self):
        await self.http.aclose()

    @observed('rerank.request', 'reranker', capture=('query',), output=False)
    async def rerank(self, query, documents):
        """Mỗi tài liệu một điểm, theo thứ tự đầu vào."""
        if not documents or len(documents) > 64:
            raise ValueError('Rerank batch must contain 1..64 documents')
        model = self.settings.RERANK_MODEL
        annotate(model=model, input_count=len(documents))
        response = await self.http.post(self.settings.RERANK_PATH, json={
            'model': model, 'query': query, 'documents': documents, 'top_n': len(documents)})
        response.raise_for_status()
        data = response.json()
        results = data.get('results') if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise ValueError('Unexpected rerank response')
        scores = {}
        for item in results:
            index = item.get('index') if isinstance(item, dict) else None
            score = item.get('relevance_score') if isinstance(item, dict) else None
            if (type(index) is not int or not 0 <= index < len(documents) or index in scores
                    or type(score) not in (int, float) or not math.isfinite(score)):
                raise ValueError('Invalid rerank result')
            scores[index] = float(score)
        if len(scores) != len(documents):
            raise ValueError('Incomplete rerank result')
        record_usage(model, 'rerank', (data.get('usage') or {}).get('total_tokens'))
        return [scores[i] for i in range(len(documents))]
