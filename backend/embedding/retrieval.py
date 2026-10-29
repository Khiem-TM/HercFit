from observability import observed, annotate, span
import json
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from fastapi import HTTPException
from models.foods import normalize_food_text

class SearchRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query: str=Field(min_length=1,max_length=1000)
    sport: str | None=Field(default=None,max_length=80)
    language: str | None=Field(default=None,max_length=30)
    topic: str | None=Field(default=None,max_length=100)
    limit: int=Field(default=6,ge=1,le=10)

def fuse(dense, keyword, k=60):
    scores={}
    for ranking in (dense,keyword):
        for rank,item in enumerate(ranking,1): scores[item]=scores.get(item,0)+1/(k+rank)
    return sorted(scores,key=lambda item:(-scores[item],str(item)))

@observed('rag.search', 'retriever', capture=('request',))
async def search(session, request, settings, client):
    if not settings.RAG_ENABLED: raise HTTPException(503,'RAG_DISABLED')
    # Embed before acquiring a database connection; slow providers must not hold
    # the backend's small shared connection pool.
    vector=(await client.embed([request.query]))[0]
    profile=(await session.execute(text('SELECT id FROM knowledge_profiles WHERE active'))).scalar_one_or_none()
    if profile!=settings.profile_id: raise HTTPException(503,'RAG_PROFILE_NOT_READY')
    filters={k:getattr(request,k) for k in ('sport','language','topic') if getattr(request,k) is not None}
    params={'profile':profile,'vector':json.dumps(vector),'query':normalize_food_text(request.query),'filters':json.dumps(filters)}
    base='''FROM knowledge_chunks c JOIN knowledge_revisions r ON r.id=c.revision_id
        JOIN knowledge_documents d ON d.id=r.document_id
        JOIN knowledge_embeddings e ON e.chunk_id=c.id AND e.profile_id=:profile
        WHERE d.active_revision=r.id AND r.review_status='APPROVED'
        AND COALESCE(r.metadata->>'visibility','authenticated')='authenticated'
        AND r.metadata @> CAST(:filters AS jsonb)'''
    with span('rag.dense', 'retriever'):
        dense=(await session.execute(text('SELECT c.id '+base+' ORDER BY e.embedding <=> CAST(:vector AS vector),c.id LIMIT 20'),params)).scalars().all()
    with span('rag.keyword', 'retriever'):
        keyword=(await session.execute(text('SELECT c.id '+base+" AND c.search_vector @@ plainto_tsquery('simple',:query) ORDER BY ts_rank_cd(c.search_vector,plainto_tsquery('simple',:query)) DESC,c.id LIMIT 20"),params)).scalars().all()
    with span('rag.fuse', 'retriever'):
        ids=fuse(dense,keyword)[:request.limit]
    annotate(result_count=len(ids), status='ok' if ids else 'empty')
    if not ids: return {'chunks':[],'status':'empty','profile_id':profile}
    rows=(await session.execute(text('''SELECT c.id,c.content,c.heading,c.page,c.revision_id,r.version,
        d.source_key,COALESCE(r.metadata->>'title',d.title) AS title,r.metadata->>'source_url' AS source_url FROM knowledge_chunks c JOIN knowledge_revisions r ON r.id=c.revision_id
        JOIN knowledge_documents d ON d.id=r.document_id WHERE c.id=ANY(:ids)
        AND d.active_revision=r.id AND r.review_status='APPROVED' '''),{'ids':ids})).mappings().all()
    by_id={r['id']:r for r in rows}; selected=[]; remaining=18000
    for ident in ids:
        if ident not in by_id: continue
        row=dict(by_id[ident]); row['content']=row['content'][:remaining]; remaining-=len(row['content'])
        row['id']=str(row['id']); row['revision_id']=str(row['revision_id']); selected.append(row)
        if remaining<=0: break
    return {'chunks':selected,'status':'ok','profile_id':profile}
