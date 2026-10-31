from agentic.observability import observed, annotate
import math
import httpx


class RerankClient:
    """Cross-encoder relevance scores from an OpenAI-style /rerank endpoint."""

    def __init__(self, settings, transport=None):
        settings.check_embedding()
        self.settings=settings
        headers={'Authorization':'Bearer '+settings.EMBEDDING_API_KEY.get_secret_value()} if settings.EMBEDDING_API_KEY else {}
        self.http=httpx.AsyncClient(base_url=settings.EMBEDDING_BASE_URL.rstrip('/')+'/',
            headers=headers,timeout=settings.RERANK_TIMEOUT_SECONDS,transport=transport,follow_redirects=False)

    async def close(self):
        await self.http.aclose()

    @observed('rerank.request', 'reranker', capture=('query',), output=False)
    async def rerank(self, query, documents):
        """One score per document, in input order."""
        if not documents or len(documents)>64:
            raise ValueError('Rerank batch must contain 1..64 documents')
        annotate(model=self.settings.RERANK_MODEL, input_count=len(documents))
        response=await self.http.post(self.settings.RERANK_PATH,json={'model':self.settings.RERANK_MODEL,'query':query,
                                                                      'documents':documents,'top_n':len(documents)})
        response.raise_for_status()
        data=response.json()
        results=data.get('results') if isinstance(data,dict) else None
        if not isinstance(results,list):
            raise ValueError('Unexpected rerank response')
        scores={}
        for item in results:
            index=item.get('index') if isinstance(item,dict) else None
            score=item.get('relevance_score') if isinstance(item,dict) else None
            if (type(index) is not int or not 0<=index<len(documents) or index in scores
                    or type(score) not in (int,float) or not math.isfinite(score)):
                raise ValueError('Invalid rerank result')
            scores[index]=float(score)
        if len(scores)!=len(documents):
            raise ValueError('Incomplete rerank result')
        tokens=(data.get('usage') or {}).get('total_tokens')
        annotate(ls_model_name=self.settings.RERANK_MODEL, hercfit_provider='rerank', cost_status='unknown')
        if type(tokens) is int and tokens>=0:
            annotate(usage_metadata={'input_tokens':tokens,'output_tokens':0,'total_tokens':tokens})
        return [scores[i] for i in range(len(documents))]
