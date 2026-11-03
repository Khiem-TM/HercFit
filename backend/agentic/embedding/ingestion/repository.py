"""Ghi và vòng đời của tài liệu, revision, chunk và job do người vận hành sở hữu. Truy hồi không bao giờ gọi module này."""
import hashlib
import json
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from agentic.embedding.core.text import normalize_text
from agentic.embedding.ingestion.preparation import load_prepared
from agentic.observability import durable_context, observed


class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_key: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=500)
    filename: str
    license: str = Field(min_length=1, max_length=1000)
    # Mỗi chunk đến từ `prepare`, bước này đếm token bằng tokenizer E5 thật.
    chunks_filename: str
    chunks_sha256: str | None = None
    content_sha256: str | None = None
    author: str | None = None
    edition: str | None = None
    processing: dict = Field(default_factory=dict)
    source_url: str | None = None
    sport: str | None = None
    topic: str | None = None
    subtopic: str | None = None
    difficulty: str | None = None
    target_population: str | None = None
    document_type: str | None = None
    language: str | None = None
    published_at: str | None = None


async def ensure_profile(session, settings):
    settings.check_embedding()
    await session.execute(text('''INSERT INTO knowledge_profiles(id,model,dimension) VALUES (:id,:model,:dim)
        ON CONFLICT DO NOTHING'''),
        {'id': settings.profile_id, 'model': settings.EMBEDDING_MODEL, 'dim': settings.EMBEDDING_DIMENSION})


@observed('knowledge.ingest', output=False)
async def enqueue(session, settings, manifest):
    content, prepared_chunks = load_prepared(settings, manifest)
    metadata = manifest.model_dump(exclude={'filename', 'source_key', 'chunks_filename'}, exclude_none=True)
    metadata['visibility'] = 'authenticated'
    digest = json.dumps({'content': content, 'metadata': metadata}, sort_keys=True, ensure_ascii=False)
    sha = hashlib.sha256(digest.encode()).hexdigest()
    await ensure_profile(session, settings)
    await session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),
                          {'key': 'knowledge:' + manifest.source_key})
    doc = (await session.execute(text('SELECT id FROM knowledge_documents WHERE source_key=:key'),
                                 {'key': manifest.source_key})).scalar_one_or_none()
    if doc is None:
        doc = uuid4()
        await session.execute(text('''INSERT INTO knowledge_documents(id,source_key,title,source_url,license)
            VALUES (:id,:key,:title,:url,:license)'''), {
            'id': doc, 'key': manifest.source_key, 'title': manifest.title,
            'url': manifest.source_url, 'license': manifest.license})
    existing = (await session.execute(text('SELECT id FROM knowledge_revisions WHERE document_id=:id AND content_hash=:hash'),
                                      {'id': doc, 'hash': sha})).scalar_one_or_none()
    if existing:
        await enqueue_index(session, existing, settings.profile_id)
        return str(existing)
    revision = uuid4()
    version = (await session.execute(text('SELECT COALESCE(MAX(version),0)+1 FROM knowledge_revisions WHERE document_id=:id'),
                                     {'id': doc})).scalar_one()
    await session.execute(text('''INSERT INTO knowledge_revisions(id,document_id,version,content_hash,content,metadata)
        VALUES (:id,:doc,:version,:hash,:content,CAST(:metadata AS jsonb))'''), {
        'id': revision, 'doc': doc, 'version': version, 'hash': sha, 'content': content,
        'metadata': json.dumps(metadata)})
    for index, chunk in enumerate(prepared_chunks):
        # Cùng cách chuẩn hoá như phía truy vấn; knowledge_document() đặt trọng số cho tiêu đề và chọn cấu hình ngôn ngữ.
        await session.execute(text('''INSERT INTO knowledge_chunks(id,revision_id,position,heading,page,page_end,page_label,content,search_vector)
            VALUES (:id,:revision,:position,:heading,:page,:page_end,:page_label,:content,
            knowledge_document(:language,:normalized_heading,:normalized))'''), {
            **chunk, 'id': uuid4(), 'revision': revision, 'position': index, 'language': manifest.language or '',
            'page_end': chunk.get('page_end') or chunk['page'], 'page_label': chunk.get('page_label'),
            'normalized_heading': normalize_text(chunk['heading'] or ''), 'normalized': normalize_text(chunk['content'])})
    await enqueue_index(session, revision, settings.profile_id)
    return str(revision)


async def enqueue_index(session, revision, profile):
    trace = durable_context()
    await session.execute(text('''INSERT INTO knowledge_jobs(id,revision_id,profile_id,trace_context)
        VALUES (:id,:revision,:profile,CAST(:trace AS jsonb)) ON CONFLICT(revision_id,profile_id) DO NOTHING'''),
        {'id': uuid4(), 'revision': revision, 'profile': profile, 'trace': json.dumps(trace) if trace else None})


async def reindex(session, settings):
    """Xếp hàng index cho mọi revision đã duyệt dưới profile hiện tại (trước khi `activate` profile mới)."""
    await ensure_profile(session, settings)
    revisions = (await session.execute(text(
        "SELECT id FROM knowledge_revisions WHERE review_status IN ('APPROVED','REVIEWED')"))).scalars().all()
    for revision in revisions:
        await enqueue_index(session, revision, settings.profile_id)


async def retry_job(session, job):
    await session.execute(text('''UPDATE knowledge_jobs SET status='QUEUED',attempts=0,available_at=now(),error_code=NULL
        WHERE id=:id AND status='FAILED' '''), {'id': job})


async def publish_ready(session, revision):
    # Tuần tự hoá việc xuất bản và thu hồi cho tài liệu này.
    row = (await session.execute(text('''SELECT r.document_id,r.review_status,r.version FROM knowledge_revisions r
        JOIN knowledge_documents d ON d.id=r.document_id WHERE r.id=:id FOR UPDATE OF d,r'''),
        {'id': revision})).mappings().one()
    if row['review_status'] != 'APPROVED':
        return
    ready = (await session.execute(text('''SELECT EXISTS(SELECT 1 FROM knowledge_jobs j JOIN knowledge_profiles p ON p.id=j.profile_id
        WHERE j.revision_id=:id AND j.status='INDEXED' AND p.active)'''), {'id': revision})).scalar_one()
    if not ready:
        return
    current = (await session.execute(text('''SELECT r.version FROM knowledge_documents d
        JOIN knowledge_revisions r ON r.id=d.active_revision WHERE d.id=:doc'''),
        {'doc': row['document_id']})).scalar_one_or_none()
    if current and current > row['version']:
        return
    await session.execute(text('''UPDATE knowledge_revisions SET review_status='SUPERSEDED'
        WHERE id=(SELECT active_revision FROM knowledge_documents WHERE id=:doc) AND id<>:id'''),
        {'doc': row['document_id'], 'id': revision})
    await session.execute(text('UPDATE knowledge_documents SET active_revision=:id WHERE id=:doc'),
                          {'id': revision, 'doc': row['document_id']})


REVIEW_STATES = {'review': 'REVIEWED', 'approve': 'APPROVED', 'reject': 'REJECTED', 'stale': 'STALE', 'delete': 'REJECTED'}


async def review(session, revision, action, reviewer):
    if action not in REVIEW_STATES or not reviewer.strip():
        raise ValueError('Action and reviewer are required')
    row = (await session.execute(text('''SELECT r.review_status,r.document_id FROM knowledge_revisions r
        JOIN knowledge_documents d ON d.id=r.document_id WHERE r.id=:id FOR UPDATE OF d,r'''),
        {'id': revision})).mappings().one()
    if action == 'approve' and row['review_status'] != 'REVIEWED':
        raise ValueError('Review before approval')
    await session.execute(text('''UPDATE knowledge_revisions SET review_status=:status,reviewer=:reviewer,reviewed_at=now()
        WHERE id=:id'''), {'id': revision, 'status': REVIEW_STATES[action], 'reviewer': reviewer})
    if action in {'reject', 'stale', 'delete'}:
        await session.execute(text('UPDATE knowledge_documents SET active_revision=NULL WHERE active_revision=:id'),
                              {'id': revision})
    elif action == 'approve':
        await publish_ready(session, revision)


async def activate(session, profile):
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('knowledge:profile',0))"))
    # Mọi tài liệu đã xuất bản cần một bản sửa đổi đã duyệt, bản đang hoạt động hoặc bản thay thế mới hơn,
    # đã được lập chỉ mục cho hồ sơ đích; publish_ready bên dưới sau đó nâng bản thay thế lên. Nhờ vậy
    # một bản sửa đổi chia chunk lại và một hồ sơ embedding mới có thể cùng lên production.
    missing = (await session.execute(text('''SELECT count(*) FROM knowledge_documents d
        JOIN knowledge_revisions active ON active.id=d.active_revision
        WHERE NOT EXISTS(SELECT 1 FROM knowledge_revisions r JOIN knowledge_jobs j ON j.revision_id=r.id
            WHERE r.document_id=d.id AND r.review_status='APPROVED' AND r.version>=active.version
            AND j.profile_id=:profile AND j.status='INDEXED')'''), {'profile': profile})).scalar_one()
    if missing:
        raise ValueError('Reindex every published revision before switching profile')
    if not (await session.execute(text('SELECT 1 FROM knowledge_profiles WHERE id=:id'), {'id': profile})).scalar_one_or_none():
        raise ValueError('Unknown profile')
    await session.execute(text('UPDATE knowledge_profiles SET active=false WHERE active'))
    await session.execute(text('UPDATE knowledge_profiles SET active=true WHERE id=:id'), {'id': profile})
    revisions = (await session.execute(text(
        "SELECT id FROM knowledge_revisions WHERE review_status='APPROVED' ORDER BY version"))).scalars().all()
    for revision in revisions:
        await publish_ready(session, revision)


async def coverage(session, revision, profile):
    """Số chunk và số vector của một revision dưới profile; thiếu dù một vector là lỗi."""
    row = (await session.execute(text('''SELECT r.id, r.review_status, d.active_revision=r.id AS published,
        count(c.id) AS chunks, count(e.chunk_id) AS embeddings FROM knowledge_revisions r
        JOIN knowledge_documents d ON d.id=r.document_id
        LEFT JOIN knowledge_chunks c ON c.revision_id=r.id
        LEFT JOIN knowledge_embeddings e ON e.chunk_id=c.id AND e.profile_id=:profile
        WHERE r.id=:id GROUP BY r.id,d.active_revision'''), {'id': revision, 'profile': profile})).mappings().one()
    return dict(row)


async def recent_status(session, limit=100):
    rows = (await session.execute(text('''SELECT r.id,r.version,r.review_status,r.reviewer,j.profile_id,j.status,j.attempts,j.error_code
        FROM knowledge_revisions r LEFT JOIN knowledge_jobs j ON j.revision_id=r.id
        ORDER BY r.created_at DESC LIMIT :limit'''), {'limit': limit})).mappings().all()
    return [dict(r) for r in rows]
