import math
from collections import OrderedDict
from time import monotonic

from agentic.embedding.core.provider import provider_http, record_usage
from agentic.observability import annotate, observed

# Cache vector truy vấn theo văn bản chính xác (không phải cache ngữ nghĩa): câu hỏi lặp lại hoặc thử lại bỏ qua
# lượt gọi nhà cung cấp. Các đoạn văn được worker tiếp nhận embed một lần và không bao giờ được cache.
QUERY_CACHE_SIZE = 512
QUERY_CACHE_SECONDS = 3600
E5_MODEL = 'multilingual-e5-large'


class EmbeddingClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = provider_http(settings, settings.EMBEDDING_TIMEOUT_SECONDS, transport)
        self.cache = OrderedDict()

    async def close(self):
        await self.http.aclose()

    async def embed(self, texts, *, input_type='query'):
        if not texts or len(texts) > 32:
            raise ValueError('Embedding batch must contain 1..32 texts')
        if input_type not in {'query', 'passage'}:
            raise ValueError('input_type must be query or passage')
        if input_type != 'query':
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

    @observed('embedding.request', 'embedding', capture=('texts',), output=False)
    async def request(self, texts, input_type):
        model = self.settings.EMBEDDING_MODEL
        # Truy hồi E5 cần tiền tố bất đối xứng, kể cả với đầu vào không phải tiếng Anh.
        if model.rsplit('/', 1)[-1] == E5_MODEL:
            prefix = input_type + ': '
            texts = [prefix + text.removeprefix(prefix) for text in texts]
        annotate(model=model, input_count=len(texts))
        response = await self.http.post('embeddings', json={'model': model, 'input': texts})
        response.raise_for_status()
        data = response.json()
        usage = data.get('usage') or {}
        record_usage(model, 'embedding', usage.get('prompt_tokens', usage.get('total_tokens')))
        rows = sorted(data['data'], key=lambda r: r['index'])
        if [r['index'] for r in rows] != list(range(len(texts))):
            raise ValueError('Embedding response indices mismatch')
        vectors = [r['embedding'] for r in rows]
        for vector in vectors:
            if (len(vector) != self.settings.EMBEDDING_DIMENSION or not any(vector)
                    or not all(type(n) in (int, float) and math.isfinite(n) for n in vector)):
                raise ValueError('Invalid embedding vector/dimension')
        return vectors
