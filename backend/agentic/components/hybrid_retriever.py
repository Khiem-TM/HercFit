"""Adapter for the backend's approved-document hybrid retrieval.

The backend owns pgvector + PostgreSQL full-text search, reciprocal-rank fusion,
reranking and the relevance threshold. This adapter preserves its HTTP contract;
it does not introduce BM25 or create a second index inside the agent process.
"""


async def retrieve_knowledge(backend, token, query, *, queries=(), limit=4):
    """(documents, status). A 'low_relevance' status means the knowledge base does not cover the question."""
    body = {'query': query, 'limit': limit}
    extra = [q for q in dict.fromkeys(queries) if q and q != query][:3]
    if extra:
        body['queries'] = extra
    data = await backend.request('POST', '/api/knowledge/search', token, body=body)
    documents = {}
    for row in data['chunks'][:limit]:
        identifier = 'kb:' + row['id']
        documents[identifier] = {**row, 'url': row.get('source_url') or '', 'source_id': identifier}
    return documents, data.get('status', 'ok')
