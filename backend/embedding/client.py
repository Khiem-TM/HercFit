from agentic.observability import observed, annotate
from collections import OrderedDict
from time import monotonic
import math
import httpx

# Cache vector truy vấn theo văn bản chính xác (không phải cache ngữ nghĩa): câu hỏi lặp lại hoặc thử lại bỏ qua
# lượt gọi nhà cung cấp. Các đoạn văn được worker tiếp nhận embed một lần và không bao giờ được cache.
QUERY_CACHE_SIZE=512
QUERY_CACHE_SECONDS=3600

class EmbeddingClient:
    def __init__(self, settings, transport=None):
        settings.check_embedding()
        self.settings=settings
        headers={'Authorization':'Bearer '+settings.EMBEDDING_API_KEY.get_secret_value()} if settings.EMBEDDING_API_KEY else {}
        self.http=httpx.AsyncClient(base_url=settings.EMBEDDING_BASE_URL.rstrip('/')+'/',
            headers=headers,timeout=settings.EMBEDDING_TIMEOUT_SECONDS,transport=transport,follow_redirects=False)
        self.cache=OrderedDict()

    async def close(self):
        await self.http.aclose()

    async def embed(self, texts, *, input_type="query"):
        if not texts or len(texts)>32:
            raise ValueError('Embedding batch must contain 1..32 texts')
        if input_type not in {"query", "passage"}:
            raise ValueError("input_type must be query or passage")
        if input_type!="query":
            return await self.request(texts,input_type)
        now=monotonic()
        for text in [t for t,(at,_) in self.cache.items() if now-at>QUERY_CACHE_SECONDS]:
            del self.cache[text]
        missing=[t for t in dict.fromkeys(texts) if t not in self.cache]
        if missing:
            for text,vector in zip(missing,await self.request(missing,input_type)):
                self.cache[text]=(now,vector)
        for text in texts:
            self.cache.move_to_end(text)
        vectors=[list(self.cache[t][1]) for t in texts]
        while len(self.cache)>QUERY_CACHE_SIZE:
            self.cache.popitem(last=False)
        return vectors

    @observed('embedding.request', 'embedding', capture=('texts',), output=False)
    async def request(self, texts, input_type):
        # Truy hồi E5 cần tiền tố bất đối xứng, kể cả với đầu vào không phải tiếng Anh.
        if self.settings.EMBEDDING_MODEL.rsplit("/", 1)[-1] == "multilingual-e5-large":
            prefix = input_type + ": "
            texts = [prefix + text.removeprefix(prefix) for text in texts]
        annotate(model=self.settings.EMBEDDING_MODEL, input_count=len(texts))
        response=await self.http.post('embeddings',json={'model':self.settings.EMBEDDING_MODEL,'input':texts})
        response.raise_for_status()
        data = response.json()
        usage = data.get('usage') or {}
        tokens = usage.get('prompt_tokens', usage.get('total_tokens'))
        annotate(ls_model_name=self.settings.EMBEDDING_MODEL, hercfit_provider='embedding', cost_status='unknown')
        if type(tokens) is int and tokens >= 0:
            annotate(usage_metadata={'input_tokens': tokens, 'output_tokens': 0, 'total_tokens': tokens})
        rows=sorted(data['data'],key=lambda r:r['index'])
        if [r['index'] for r in rows] != list(range(len(texts))):
            raise ValueError('Embedding response indices mismatch')
        vectors=[r['embedding'] for r in rows]
        for v in vectors:
            if len(v)!=self.settings.EMBEDDING_DIMENSION or not all(type(n) in (int,float) and math.isfinite(n) for n in v) or not any(v):
                raise ValueError('Invalid embedding vector/dimension')
        return vectors
