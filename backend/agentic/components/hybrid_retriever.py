"""Adapter cho bộ truy hồi lai trên tài liệu đã duyệt của backend.

Backend quản lý pgvector + tìm kiếm toàn văn PostgreSQL, kết hợp xếp hạng nghịch đảo (RRF),
xếp hạng lại và ngưỡng liên quan. Adapter này giữ nguyên hợp đồng HTTP của nó;
không đưa BM25 vào hay tạo chỉ mục thứ hai trong tiến trình agent.
"""


async def retrieve_knowledge(backend, token, query, *, queries=(), limit=4):
    """(documents, status). Trạng thái 'low_relevance' nghĩa là cơ sở tri thức không bao quát câu hỏi."""
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
