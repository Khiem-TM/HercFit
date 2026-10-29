from observability import observed, annotate
import math
import httpx

class EmbeddingClient:
    def __init__(self, settings, transport=None):
        settings.check_embedding()
        self.settings=settings
        headers={'Authorization':'Bearer '+settings.EMBEDDING_API_KEY.get_secret_value()} if settings.EMBEDDING_API_KEY else {}
        self.http=httpx.AsyncClient(base_url=settings.EMBEDDING_BASE_URL.rstrip('/')+'/',
            headers=headers,timeout=settings.EMBEDDING_TIMEOUT_SECONDS,transport=transport,follow_redirects=False)

    async def close(self):
        await self.http.aclose()

    @observed('embedding.request', 'embedding', capture=('texts',), output=False)
    async def embed(self, texts):
        if not texts or len(texts)>32:
            raise ValueError('Embedding batch must contain 1..32 texts')
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
