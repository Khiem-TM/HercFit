"""Operator-owned curation. Research results never call this module."""
from agentic.observability import observed, durable_context
import hashlib
import json
from uuid import uuid4
from sqlalchemy import text
from pydantic import BaseModel, ConfigDict, Field
from domains.catalog.models.foods import normalize_food_text
from knowledge_ingestion.preparation import load_prepared

class Manifest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_key: str=Field(min_length=1,max_length=300)
    title: str=Field(min_length=1,max_length=500)
    filename: str
    license: str=Field(min_length=1,max_length=1000)
    # Every chunk comes from `prepare`, which counts tokens with the real E5 tokenizer.
    chunks_filename: str
    chunks_sha256: str | None = None
    content_sha256: str | None = None
    author: str | None = None
    edition: str | None = None
    processing: dict = Field(default_factory=dict)
    source_url: str | None=None
    sport: str | None=None
    topic: str | None=None
    subtopic: str | None=None
    difficulty: str | None=None
    target_population: str | None=None
    document_type: str | None=None
    language: str | None=None
    published_at: str | None=None

async def ensure_profile(session, settings):
    settings.check_embedding()
    await session.execute(text('''INSERT INTO knowledge_profiles(id,model,dimension) VALUES (:id,:model,:dim)
        ON CONFLICT DO NOTHING'''),{'id':settings.profile_id,'model':settings.EMBEDDING_MODEL,'dim':settings.EMBEDDING_DIMENSION})

@observed('knowledge.ingest', output=False)
async def enqueue(session, settings, manifest):
    content, prepared_chunks = load_prepared(settings, manifest)
    metadata=manifest.model_dump(exclude={'filename','source_key','chunks_filename'},exclude_none=True)
    metadata['visibility']='authenticated'
    sha=hashlib.sha256(json.dumps({'content':content,'metadata':metadata},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    await ensure_profile(session,settings)
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{'key':'knowledge:'+manifest.source_key})
    doc=(await session.execute(text('SELECT id FROM knowledge_documents WHERE source_key=:key'),{'key':manifest.source_key})).scalar_one_or_none()
    if doc is None:
        doc=uuid4()
        await session.execute(text('''INSERT INTO knowledge_documents(id,source_key,title,source_url,license)
            VALUES (:id,:key,:title,:url,:license)'''),{'id':doc,'key':manifest.source_key,'title':manifest.title,'url':manifest.source_url,'license':manifest.license})
    existing=(await session.execute(text('SELECT id FROM knowledge_revisions WHERE document_id=:id AND content_hash=:hash'),{'id':doc,'hash':sha})).scalar_one_or_none()
    if existing:
        await enqueue_index(session,existing,settings.profile_id)
        return str(existing)
    revision=uuid4()
    version=(await session.execute(text('SELECT COALESCE(MAX(version),0)+1 FROM knowledge_revisions WHERE document_id=:id'),{'id':doc})).scalar_one()
    await session.execute(text('''INSERT INTO knowledge_revisions(id,document_id,version,content_hash,content,metadata)
        VALUES (:id,:doc,:version,:hash,:content,CAST(:metadata AS jsonb))'''),
        {'id':revision,'doc':doc,'version':version,'hash':sha,'content':content,'metadata':json.dumps(metadata)})
    for index,chunk in enumerate(prepared_chunks):
        # Same normalization as the query side; knowledge_document() weighs the heading and picks the language config.
        await session.execute(text('''INSERT INTO knowledge_chunks(id,revision_id,position,heading,page,page_end,page_label,content,search_vector)
            VALUES (:id,:revision,:position,:heading,:page,:page_end,:page_label,:content,
            knowledge_document(:language,:normalized_heading,:normalized))'''),
            {**chunk,'id':uuid4(),'revision':revision,'position':index,'language':manifest.language or '',
             'page_end':chunk.get('page_end') or chunk['page'],'page_label':chunk.get('page_label'),
             'normalized_heading':normalize_food_text(chunk['heading'] or ''),'normalized':normalize_food_text(chunk['content'])})
    await enqueue_index(session,revision,settings.profile_id)
    return str(revision)

async def enqueue_index(session, revision, profile):
    await session.execute(text('''INSERT INTO knowledge_jobs(id,revision_id,profile_id,trace_context) VALUES (:id,:revision,:profile,CAST(:trace AS jsonb))
        ON CONFLICT(revision_id,profile_id) DO NOTHING'''),{'id':uuid4(),'revision':revision,'profile':profile,'trace':json.dumps(durable_context()) if durable_context() else None})

async def publish_ready(session, revision):
    # Serialize publication and revocation for this document.
    row=(await session.execute(text('''SELECT r.document_id,r.review_status,r.version FROM knowledge_revisions r
        JOIN knowledge_documents d ON d.id=r.document_id WHERE r.id=:id FOR UPDATE OF d,r'''),{'id':revision})).mappings().one()
    if row['review_status']!='APPROVED': return
    ready=(await session.execute(text('''SELECT EXISTS(SELECT 1 FROM knowledge_jobs j JOIN knowledge_profiles p ON p.id=j.profile_id
        WHERE j.revision_id=:id AND j.status='INDEXED' AND p.active)'''),{'id':revision})).scalar_one()
    if not ready: return
    current=(await session.execute(text('''SELECT r.version FROM knowledge_documents d JOIN knowledge_revisions r ON r.id=d.active_revision
        WHERE d.id=:doc'''),{'doc':row['document_id']})).scalar_one_or_none()
    if current and current>row['version']: return
    await session.execute(text('''UPDATE knowledge_revisions SET review_status='SUPERSEDED'
        WHERE id=(SELECT active_revision FROM knowledge_documents WHERE id=:doc) AND id<>:id'''),{'doc':row['document_id'],'id':revision})
    await session.execute(text('UPDATE knowledge_documents SET active_revision=:id WHERE id=:doc'),{'id':revision,'doc':row['document_id']})

async def review(session, revision, action, reviewer):
    states={'review':'REVIEWED','approve':'APPROVED','reject':'REJECTED','stale':'STALE','delete':'REJECTED'}
    if action not in states or not reviewer.strip(): raise ValueError('Action and reviewer are required')
    row=(await session.execute(text('''SELECT r.review_status,r.document_id FROM knowledge_revisions r
        JOIN knowledge_documents d ON d.id=r.document_id WHERE r.id=:id FOR UPDATE OF d,r'''),{'id':revision})).mappings().one()
    if action=='approve' and row['review_status']!='REVIEWED': raise ValueError('Review before approval')
    await session.execute(text('''UPDATE knowledge_revisions SET review_status=:status,reviewer=:reviewer,reviewed_at=now()
        WHERE id=:id'''),{'id':revision,'status':states[action],'reviewer':reviewer})
    if action in {'reject','stale','delete'}:
        await session.execute(text('UPDATE knowledge_documents SET active_revision=NULL WHERE active_revision=:id'),{'id':revision})
    elif action=='approve': await publish_ready(session,revision)

async def activate(session, profile):
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('knowledge:profile',0))"))
    # Every published document needs an approved revision, the active one or a newer replacement,
    # indexed for the target profile; publish_ready below then promotes the replacement. This lets a
    # re-chunked revision and a new embedding profile go live together.
    missing=(await session.execute(text('''SELECT count(*) FROM knowledge_documents d
        JOIN knowledge_revisions active ON active.id=d.active_revision
        WHERE NOT EXISTS(SELECT 1 FROM knowledge_revisions r JOIN knowledge_jobs j ON j.revision_id=r.id
            WHERE r.document_id=d.id AND r.review_status='APPROVED' AND r.version>=active.version
            AND j.profile_id=:profile AND j.status='INDEXED')'''),{'profile':profile})).scalar_one()
    if missing: raise ValueError('Reindex every published revision before switching profile')
    if not (await session.execute(text('SELECT 1 FROM knowledge_profiles WHERE id=:id'),{'id':profile})).scalar_one_or_none():
        raise ValueError('Unknown profile')
    await session.execute(text('UPDATE knowledge_profiles SET active=false WHERE active'))
    await session.execute(text('UPDATE knowledge_profiles SET active=true WHERE id=:id'),{'id':profile})
    revisions=(await session.execute(text("SELECT id FROM knowledge_revisions WHERE review_status='APPROVED' ORDER BY version"))).scalars().all()
    for revision in revisions: await publish_ready(session,revision)
