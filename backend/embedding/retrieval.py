from agentic.observability import observed, annotate, span
import json
from collections import defaultdict
from time import perf_counter
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from fastapi import HTTPException
from models.foods import normalize_food_text

class SearchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query: str=Field(min_length=1,max_length=1000)
    # Other phrasings of the same question, e.g. an English one for an English corpus.
    queries: list[Annotated[str,Field(min_length=1,max_length=300)]]=Field(default_factory=list,max_length=3)
    sport: str | None=Field(default=None,max_length=80)
    language: str | None=Field(default=None,max_length=30)
    topic: str | None=Field(default=None,max_length=100)
    limit: int=Field(default=6,ge=1,le=10)

class SearchOptions(BaseModel):
    """Stage switches for offline evaluation; never part of the HTTP request."""
    model_config=ConfigDict(extra='forbid')
    multi: bool=True
    keyword: bool=True
    rerank: bool=True
    diversify: bool=True
    # False disables both relevance thresholds (calibration runs); explicit values override settings.
    thresholds: bool=True
    min_score: float | None=None
    min_similarity: float | None=None
    candidates: int | None=Field(default=None,ge=1,le=64)
    debug: bool=False

def fuse(*rankings, k=60):
    """Reciprocal-rank fusion of any number of ranked id lists."""
    scores={}
    for ranking in rankings:
        for rank,item in enumerate(ranking,1): scores[item]=scores.get(item,0)+1/(k+rank)
    return sorted(scores,key=lambda item:(-scores[item],str(item)))

ELIGIBLE='''FROM knowledge_chunks c JOIN knowledge_revisions r ON r.id=c.revision_id
        JOIN knowledge_documents d ON d.id=r.document_id
        JOIN knowledge_embeddings e ON e.chunk_id=c.id AND e.profile_id=:profile
        WHERE d.active_revision=r.id AND r.review_status='APPROVED'
        AND COALESCE(r.metadata->>'visibility','authenticated')='authenticated'
        AND r.metadata @> CAST(:filters AS jsonb)'''

# One round trip: a dense and a keyword list per query, each a bounded top-N scan. The
# tsquery is built once per query and document language class, as knowledge_ts_config().
# MATERIALIZED keeps the text->vector cast and tsquery parse from repeating for every row.
CANDIDATES='''WITH qv AS MATERIALIZED (SELECT ord,CAST(v AS vector) AS vec
        FROM jsonb_array_elements_text(CAST(:vectors AS jsonb)) WITH ORDINALITY AS t(v,ord)),
    qt AS MATERIALIZED (SELECT ord,knowledge_query('en',q) AS q_en,knowledge_query('',q) AS q_other
        FROM jsonb_array_elements_text(CAST(:queries AS jsonb)) WITH ORDINALITY AS t(q,ord))
    SELECT 'dense' AS kind,qv.ord,x.id,x.score FROM qv CROSS JOIN LATERAL (
        SELECT c.id,1-(e.embedding <=> qv.vec) AS score '''+ELIGIBLE+'''
        ORDER BY e.embedding <=> qv.vec,c.id LIMIT :depth) x
    UNION ALL
    SELECT 'keyword',qt.ord,y.id,y.score FROM qt CROSS JOIN LATERAL (
        SELECT k.id,ts_rank_cd(k.search_vector,k.q) AS score FROM (
            SELECT c.id,c.search_vector,CASE WHEN COALESCE(r.metadata->>'language','')='en'
                THEN qt.q_en ELSE qt.q_other END AS q '''+ELIGIBLE+''') k
        WHERE :keyword AND k.search_vector @@ k.q ORDER BY 2 DESC,k.id LIMIT :depth) y'''

CONTENT='''SELECT c.id,c.content,c.heading,c.page,COALESCE(c.page_end,c.page) AS page_end,c.page_label,c.revision_id,r.version,
        d.source_key,COALESCE(r.metadata->>'title',d.title) AS title,r.metadata->>'source_url' AS source_url,
        r.metadata->>'language' AS language FROM knowledge_chunks c JOIN knowledge_revisions r ON r.id=c.revision_id
        JOIN knowledge_documents d ON d.id=r.document_id WHERE c.id=ANY(:ids)
        AND d.active_revision=r.id AND r.review_status='APPROVED' '''

@observed('rag.search', 'retriever', capture=('request',))
async def search(session, request, settings, client, reranker=None, options=None):
    if not settings.RAG_ENABLED: raise HTTPException(503,'RAG_DISABLED')
    options=options or SearchOptions()
    timings={}; started=perf_counter()
    queries=list(dict.fromkeys(q.strip() for q in [request.query,*(request.queries if options.multi else [])] if q.strip()))
    # Embed before acquiring a database connection; slow providers must not hold
    # the backend's small shared connection pool.
    vectors=await client.embed(queries)
    timings['embed_ms']=round((perf_counter()-started)*1000,1)
    profile=(await session.execute(text('SELECT id FROM knowledge_profiles WHERE active'))).scalar_one_or_none()
    if profile!=settings.profile_id: raise HTTPException(503,'RAG_PROFILE_NOT_READY')
    filters={k:getattr(request,k) for k in ('sport','language','topic') if getattr(request,k) is not None}
    depth=options.candidates or settings.RAG_CANDIDATES
    with span('rag.candidates', 'retriever'):
        mark=perf_counter()
        rows=(await session.execute(text(CANDIDATES),{'profile':profile,'filters':json.dumps(filters),'depth':depth,
            'vectors':json.dumps(vectors),'queries':json.dumps([normalize_food_text(q) for q in queries]),
            'keyword':options.keyword})).mappings().all()
        timings['candidates_ms']=round((perf_counter()-mark)*1000,1)
    # Both scores rank higher-is-better: cosine similarity and ts_rank_cd; ties break on id as in SQL.
    lists=defaultdict(list); similarity={}
    for row in sorted(rows,key=lambda r:(r['kind'],r['ord'],-r['score'],str(r['id']))):
        lists[row['kind'],row['ord']].append(row['id'])
        if row['kind']=='dense':
            similarity[row['id']]=max(similarity.get(row['id'],-1.0),float(row['score']))
    with span('rag.fuse', 'retriever'):
        ids=fuse(*lists.values())[:depth]
    diagnostics={'queries':len(queries),'dense_hits':sum(len(v) for (kind,_),v in lists.items() if kind=='dense'),
                 'keyword_hits':sum(len(v) for (kind,_),v in lists.items() if kind=='keyword'),'candidates':len(ids),
                 'top_similarity':round(max(similarity.values()),4) if similarity else None}
    if not ids:
        return finish({'chunks':[],'status':'empty','profile_id':profile,'rerank':'disabled'},diagnostics,timings,started,options)
    by_id={r['id']:dict(r) for r in (await session.execute(text(CONTENT),{'ids':ids})).mappings().all()}
    candidates=[by_id[i] for i in ids if i in by_id]
    # Release the connection before the external rerank call, as for the embedding call.
    await session.commit()
    # The cross-encoder scores best in the passages' language: an English paraphrase for English books.
    english=[c for c in candidates if c.get('language')=='en']
    rerank_query=next((q for q in queries if q.isascii()),request.query) if len(english)*2>len(candidates) else request.query
    status,scores=await rerank(reranker,rerank_query,candidates,options,timings)
    if scores is not None:
        order=sorted(range(len(candidates)),key=lambda i:(-scores[i],i))
        candidates=[{**candidates[i],'score':round(scores[i],4)} for i in order]
        diagnostics['top_score']=candidates[0]['score'] if candidates else None
    selected=[]; per_page=defaultdict(int); remaining=18000
    for row in candidates:
        key=(row['revision_id'],row['page'])
        if options.diversify and per_page[key]>=settings.RAG_MAX_PER_PAGE: continue
        per_page[key]+=1
        row['similarity']=round(similarity.get(row['id'],0.0),4)
        row['content']=row['content'][:remaining]; remaining-=len(row['content'])
        row.pop('language',None)
        row['id']=str(row['id']); row['revision_id']=str(row['revision_id']); selected.append(row)
        if len(selected)>=request.limit or remaining<=0: break
    result={'chunks':selected,'status':'ok' if selected else 'empty','profile_id':profile,'rerank':status}
    if selected and options.thresholds and not relevant(selected,status,settings,options):
        result.update(chunks=[],status='low_relevance')
    return finish(result,diagnostics,timings,started,options)

async def rerank(reranker,query,candidates,options,timings):
    """(status, scores); a reranker outage keeps the fused order and never fails the search."""
    if reranker is None or not options.rerank or not candidates:
        return 'disabled',None
    mark=perf_counter()
    try:
        with span('rag.rerank', 'retriever'):
            # The chapter heading gives the cross-encoder the context an isolated passage lacks.
            scores=await reranker.rerank(query,[(row['heading']+'\n' if row['heading'] else '')+row['content'] for row in candidates])
        return 'applied',scores
    except Exception as exc:
        annotate(rerank_error=type(exc).__name__)
        return 'unavailable',None
    finally:
        timings['rerank_ms']=round((perf_counter()-mark)*1000,1)

def relevant(selected,status,settings,options):
    if status=='applied':
        floor=options.min_score if options.min_score is not None else settings.RAG_MIN_RERANK_SCORE
        return floor is None or selected[0]['score']>=floor
    floor=options.min_similarity if options.min_similarity is not None else settings.RAG_MIN_DENSE_SIMILARITY
    return floor is None or max(row['similarity'] for row in selected)>=floor

def finish(result,diagnostics,timings,started,options):
    timings['total_ms']=round((perf_counter()-started)*1000,1)
    annotate(result_count=len(result['chunks']),status=result['status'],rerank=result['rerank'],
             **{k:v for k,v in diagnostics.items() if v is not None},**timings)
    if options.debug:
        result['diagnostics']={**diagnostics,'timings':timings}
    return result
