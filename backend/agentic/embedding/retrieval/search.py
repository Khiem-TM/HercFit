import json
from collections import defaultdict
from time import perf_counter
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from agentic.embedding.core.text import normalize_text
from agentic.observability import annotate, observed, span

# Ngân sách ký tự cho toàn bộ nội dung trả về trong một lần tìm kiếm.
CONTENT_BUDGET = 18000


class RetrievalUnavailable(RuntimeError):
    """Tìm kiếm không thể phục vụ; thông điệp là mã lỗi ổn định mà router trả về (503)."""


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=1000)
    # Các cách diễn đạt khác của cùng câu hỏi, ví dụ một bản tiếng Anh cho kho tiếng Anh.
    queries: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=3)
    sport: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=30)
    topic: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=6, ge=1, le=10)


class SearchOptions(BaseModel):
    """Stage switches for offline evaluation; never part of the HTTP request."""
    model_config = ConfigDict(extra='forbid')
    multi: bool = True
    keyword: bool = True
    rerank: bool = True
    diversify: bool = True
    # False tắt cả hai ngưỡng liên quan (lượt chạy hiệu chỉnh); giá trị tường minh ghi đè settings.
    thresholds: bool = True
    min_score: float | None = None
    min_similarity: float | None = None
    candidates: int | None = Field(default=None, ge=1, le=64)
    debug: bool = False


def fuse(*rankings, k=60):
    """Hợp nhất xếp hạng nghịch đảo (RRF) cho số lượng tuỳ ý danh sách id đã xếp hạng."""
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda item: (-scores[item], str(item)))


ELIGIBLE = '''FROM knowledge_chunks c JOIN knowledge_revisions r ON r.id=c.revision_id
        JOIN knowledge_documents d ON d.id=r.document_id
        JOIN knowledge_embeddings e ON e.chunk_id=c.id AND e.profile_id=:profile
        WHERE d.active_revision=r.id AND r.review_status='APPROVED'
        AND COALESCE(r.metadata->>'visibility','authenticated')='authenticated'
        AND r.metadata @> CAST(:filters AS jsonb)'''

# Một lượt gọi: mỗi truy vấn một danh sách dense và một danh sách từ khoá, mỗi danh sách quét top-N có giới hạn. tsquery
# được dựng một lần cho mỗi truy vấn và lớp ngôn ngữ tài liệu, như knowledge_ts_config().
# MATERIALIZED giữ phép ép text->vector và phân tích tsquery không lặp lại cho từng dòng.
CANDIDATES = '''WITH qv AS MATERIALIZED (SELECT ord,CAST(v AS vector) AS vec
        FROM jsonb_array_elements_text(CAST(:vectors AS jsonb)) WITH ORDINALITY AS t(v,ord)),
    qt AS MATERIALIZED (SELECT ord,knowledge_query('en',q) AS q_en,knowledge_query('',q) AS q_other
        FROM jsonb_array_elements_text(CAST(:queries AS jsonb)) WITH ORDINALITY AS t(q,ord))
    SELECT 'dense' AS kind,qv.ord,x.id,x.score FROM qv CROSS JOIN LATERAL (
        SELECT c.id,1-(e.embedding <=> qv.vec) AS score ''' + ELIGIBLE + '''
        ORDER BY e.embedding <=> qv.vec,c.id LIMIT :depth) x
    UNION ALL
    SELECT 'keyword',qt.ord,y.id,y.score FROM qt CROSS JOIN LATERAL (
        SELECT k.id,ts_rank_cd(k.search_vector,k.q) AS score FROM (
            SELECT c.id,c.search_vector,CASE WHEN COALESCE(r.metadata->>'language','')='en'
                THEN qt.q_en ELSE qt.q_other END AS q ''' + ELIGIBLE + ''') k
        WHERE :keyword AND k.search_vector @@ k.q ORDER BY 2 DESC,k.id LIMIT :depth) y'''

CONTENT = '''SELECT c.id,c.content,c.heading,c.page,COALESCE(c.page_end,c.page) AS page_end,c.page_label,c.revision_id,r.version,
        d.source_key,COALESCE(r.metadata->>'title',d.title) AS title,r.metadata->>'source_url' AS source_url,
        r.metadata->>'language' AS language FROM knowledge_chunks c JOIN knowledge_revisions r ON r.id=c.revision_id
        JOIN knowledge_documents d ON d.id=r.document_id WHERE c.id=ANY(:ids)
        AND d.active_revision=r.id AND r.review_status='APPROVED' '''


@observed('rag.search', 'retriever', capture=('request',))
async def search(session, request, settings, client, reranker=None, options=None):
    if not settings.RAG_ENABLED:
        raise RetrievalUnavailable('RAG_DISABLED')
    options = options or SearchOptions()
    timings = {}
    started = perf_counter()
    queries = list(dict.fromkeys(
        q.strip() for q in [request.query, *(request.queries if options.multi else [])] if q.strip()))
    # Embed trước khi lấy kết nối database; nhà cung cấp chậm không được giữ
    # pool kết nối dùng chung nhỏ của backend.
    vectors = await client.embed(queries)
    timings['embed_ms'] = elapsed_ms(started)
    profile = (await session.execute(text('SELECT id FROM knowledge_profiles WHERE active'))).scalar_one_or_none()
    if profile != settings.profile_id:
        raise RetrievalUnavailable('RAG_PROFILE_NOT_READY')
    filters = {k: getattr(request, k) for k in ('sport', 'language', 'topic') if getattr(request, k) is not None}
    depth = options.candidates or settings.RAG_CANDIDATES
    with span('rag.candidates', 'retriever'):
        mark = perf_counter()
        rows = (await session.execute(text(CANDIDATES), {
            'profile': profile, 'filters': json.dumps(filters), 'depth': depth, 'vectors': json.dumps(vectors),
            'queries': json.dumps([normalize_text(q) for q in queries]), 'keyword': options.keyword,
        })).mappings().all()
        timings['candidates_ms'] = elapsed_ms(mark)
    # Cả hai điểm đều xếp hạng càng cao càng tốt: độ tương đồng cosine và ts_rank_cd; bằng điểm thì xét id như trong SQL.
    lists = defaultdict(list)
    similarity = {}
    for row in sorted(rows, key=lambda r: (r['kind'], r['ord'], -r['score'], str(r['id']))):
        lists[row['kind'], row['ord']].append(row['id'])
        if row['kind'] == 'dense':
            similarity[row['id']] = max(similarity.get(row['id'], -1.0), float(row['score']))
    with span('rag.fuse', 'retriever'):
        ids = fuse(*lists.values())[:depth]
    diagnostics = {
        'queries': len(queries),
        'dense_hits': sum(len(v) for (kind, _), v in lists.items() if kind == 'dense'),
        'keyword_hits': sum(len(v) for (kind, _), v in lists.items() if kind == 'keyword'),
        'candidates': len(ids),
        'top_similarity': round(max(similarity.values()), 4) if similarity else None,
    }
    if not ids:
        result = {'chunks': [], 'status': 'empty', 'profile_id': profile, 'rerank': 'disabled'}
        return finish(result, diagnostics, timings, started, options)
    by_id = {r['id']: dict(r) for r in (await session.execute(text(CONTENT), {'ids': ids})).mappings().all()}
    candidates = [by_id[i] for i in ids if i in by_id]
    # Nhả kết nối trước lời gọi rerank bên ngoài, như với lời gọi embedding.
    await session.commit()
    # Cross-encoder chấm tốt nhất theo ngôn ngữ của đoạn văn: một bản diễn đạt tiếng Anh cho sách tiếng Anh.
    english = sum(c.get('language') == 'en' for c in candidates)
    rerank_query = next((q for q in queries if q.isascii()), request.query) if english * 2 > len(candidates) else request.query
    status, scores = await rerank(reranker, rerank_query, candidates, options, timings)
    if scores is not None:
        order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
        candidates = [{**candidates[i], 'score': round(scores[i], 4)} for i in order]
        diagnostics['top_score'] = candidates[0]['score'] if candidates else None
    selected = select(candidates, similarity, request.limit, settings.RAG_MAX_PER_PAGE if options.diversify else None)
    result = {'chunks': selected, 'status': 'ok' if selected else 'empty', 'profile_id': profile, 'rerank': status}
    if selected and options.thresholds and not relevant(selected, status, settings, options):
        result.update(chunks=[], status='low_relevance')
    return finish(result, diagnostics, timings, started, options)


def select(candidates, similarity, limit, max_per_page):
    """Giữ thứ tự xếp hạng, tối đa max_per_page chunk mỗi trang nguồn, trong ngân sách ký tự."""
    selected = []
    per_page = defaultdict(int)
    remaining = CONTENT_BUDGET
    for row in candidates:
        key = (row['revision_id'], row['page'])
        if max_per_page is not None and per_page[key] >= max_per_page:
            continue
        per_page[key] += 1
        row['similarity'] = round(similarity.get(row['id'], 0.0), 4)
        row['content'] = row['content'][:remaining]
        remaining -= len(row['content'])
        row.pop('language', None)
        row['id'] = str(row['id'])
        row['revision_id'] = str(row['revision_id'])
        selected.append(row)
        if len(selected) >= limit or remaining <= 0:
            break
    return selected


async def rerank(reranker, query, candidates, options, timings):
    """(status, scores); reranker gặp sự cố thì giữ thứ tự đã hợp nhất và không bao giờ làm hỏng lần tìm kiếm."""
    if reranker is None or not options.rerank or not candidates:
        return 'disabled', None
    mark = perf_counter()
    try:
        with span('rag.rerank', 'retriever'):
            # Tiêu đề chương cho cross-encoder ngữ cảnh mà một đoạn văn đứng riêng còn thiếu.
            documents = [(row['heading'] + '\n' if row['heading'] else '') + row['content'] for row in candidates]
            scores = await reranker.rerank(query, documents)
        return 'applied', scores
    except Exception as exc:
        annotate(rerank_error=type(exc).__name__)
        return 'unavailable', None
    finally:
        timings['rerank_ms'] = elapsed_ms(mark)


def relevant(selected, status, settings, options):
    if status == 'applied':
        floor = options.min_score if options.min_score is not None else settings.RAG_MIN_RERANK_SCORE
        return floor is None or selected[0]['score'] >= floor
    floor = options.min_similarity if options.min_similarity is not None else settings.RAG_MIN_DENSE_SIMILARITY
    return floor is None or max(row['similarity'] for row in selected) >= floor


def elapsed_ms(since):
    return round((perf_counter() - since) * 1000, 1)


def finish(result, diagnostics, timings, started, options):
    timings['total_ms'] = elapsed_ms(started)
    annotate(result_count=len(result['chunks']), status=result['status'], rerank=result['rerank'],
             **{k: v for k, v in diagnostics.items() if v is not None}, **timings)
    if options.debug:
        result['diagnostics'] = {**diagnostics, 'timings': timings}
    return result
