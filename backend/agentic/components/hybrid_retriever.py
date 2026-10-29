"""Adapter for the backend's approved-document hybrid retrieval.

The backend owns pgvector + PostgreSQL full-text search and reciprocal-rank
fusion. This adapter preserves its HTTP contract; it does not introduce BM25 or
create a second index inside the agent process.
"""


async def retrieve_knowledge(backend, token, query, *, limit=3):
    data = await backend.request('POST', '/api/knowledge/search', token, body={'query': query})
    documents = {}
    for row in data['chunks'][:limit]:
        identifier = 'kb:' + row['id']
        documents[identifier] = {**row, 'url': row.get('source_url') or '', 'source_id': identifier}
    return documents
