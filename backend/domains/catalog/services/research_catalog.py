"""Bộ giải quyết theo chủ sở hữu và finalize catalog cục bộ trong transaction."""
import hashlib
import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import text

from agentic.research.attestation import key_id, verify
from core.settings import settings
from domains.catalog.models.exercises import Exercise
from domains.catalog.models.foods import FoodItem, normalize_food_text
from domains.catalog.schemas.exercises import ExerciseRead
from domains.catalog.schemas.foods import FoodRead

MODELS = {'foods': (FoodItem, FoodRead), 'exercises': (Exercise, ExerciseRead)}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()

async def catalog_lock(session, domain):
    if domain not in MODELS:
        raise ValueError('Unknown catalog')
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {'key': 'catalog:'+domain})

async def resolve(service, domain, query):
    if domain not in MODELS:
        raise ValueError('Unknown catalog')
    normalized = normalize_food_text(query)
    if not normalized:
        raise HTTPException(422, 'Empty lookup')
    rows = (await service.session.execute(text(f'''
        SELECT c.id, c.version_id, c.name_vi, c.name_en, c.source_type,
            (c.normalized_name_vi=:q OR c.normalized_name_en=:q OR lower(c.code)=:q OR EXISTS
             (SELECT 1 FROM {domain}_aliases a WHERE a.entity_id=c.id AND a.normalized_alias=:q)) AS exact,
            similarity(c.normalized_search_text,:q) AS score
        FROM {domain} c WHERE c.is_active AND (c.source_type='SYSTEM' OR c.owner_user_id=:owner)
        AND (c.normalized_name_vi=:q OR c.normalized_name_en=:q OR lower(c.code)=:q
             OR c.normalized_search_text % :q OR strpos(c.normalized_search_text,:q)>0 OR EXISTS
             (SELECT 1 FROM {domain}_aliases a WHERE a.entity_id=c.id AND a.normalized_alias=:q))
        ORDER BY exact DESC, (c.source_type='CUSTOM') DESC, score DESC, c.id
        LIMIT 101'''), {'q':normalized, 'owner':service.user_id})).mappings().all()
    matches = [{**dict(r), 'id': str(r['id'])} for r in rows]
    exact = [r for r in matches if r['exact']]
    return {'query':normalized, 'status':'EXACT' if len(exact)==1 else 'POSSIBLE_VARIANT' if matches else 'MISSING',
            'matches':matches[:100], 'truncated':len(matches)>100,
            'fingerprint':digest([[r['id'],r['version_id']] for r in matches])}

def attest(service, domain, data):
    """Chỉ lệnh do service tra cứu ký mới mang nhãn "đã kiểm chứng bởi tra cứu"."""
    if settings.RESEARCH_ATTESTATION_SECRET is None:
        raise HTTPException(503, 'Research attestation is not configured')
    secrets = [settings.RESEARCH_ATTESTATION_SECRET.get_secret_value(),
               *(s.get_secret_value() for s in settings.RESEARCH_ATTESTATION_PREVIOUS_SECRETS)]
    secret = verify(secrets, service.user_id, domain, data, data.get('attestation'),
                    max_age=timedelta(hours=settings.RESEARCH_ATTESTATION_MAX_AGE_HOURS))
    if secret is None:
        raise HTTPException(403, 'Command is not attested by the research service')
    return {'research_verified': True, 'candidate_id': data['candidate_id'], 'key_id': key_id(secret),
            'attested_at': data['attestation']['issued_at']}

async def finalize(service, domain, command):
    await catalog_lock(service.session, domain)
    data = command.model_dump(mode='json')
    request_digest = digest(data)
    keys = {'owner':service.user_id, 'candidate':command.candidate_id, 'revision':command.candidate_revision}
    previous = (await service.session.execute(text('''SELECT digest,result FROM research_finalizations
        WHERE owner_id=:owner AND candidate_id=:candidate AND candidate_revision=:revision'''), keys)).mappings().first()
    if previous:
        if previous['digest'] != request_digest:
            raise HTTPException(409, 'Candidate revision has changed')
        # Phát lại chính xác (digest bao gồm chữ ký) trả về biên nhận kể cả sau khi hết hạn.
        return previous['result']
    provenance = attest(service, domain, data)
    # Người dùng đã quyết định dựa trên đúng các kết quả bộ giải quyết này cho truy vấn và tên ứng viên.
    found = await resolve(service, domain, command.query)
    canonical = await resolve(service, domain, command.payload.name_vi)
    if (found['truncated'] or canonical['truncated'] or found['fingerprint'] != command.expected_match_fingerprint
            or canonical['fingerprint'] != command.expected_name_fingerprint):
        raise HTTPException(409, 'Catalog changed; generate a new preview')
    matches = {m['id']: m for m in [*found['matches'], *canonical['matches']]}
    if command.resolution == 'create' and matches:
        raise HTTPException(409, 'Possible existing record; explicitly choose reuse or a distinct variant')
    if command.resolution == 'create_distinct':
        if not matches:
            raise HTTPException(422, 'No existing record to be distinct from; use create')
        if any(m['exact'] for m in canonical['matches']):
            raise HTTPException(409, 'A distinct variant needs a name no existing record uses')
        if command.aliases and any(m['exact'] for m in found['matches']):
            raise HTTPException(422, 'The query names an existing record and cannot alias a new variant')
    # Truy vấn phải mô tả đúng ứng viên thật; nếu không, một lần tìm rỗng không liên quan
    # có thể bị dùng để lách kiểm tra trùng. Một biến thể riêng có thể
    # làm rõ truy vấn ("squat" -> "goblet squat").
    query = normalize_food_text(command.query)
    names = {normalize_food_text(n) for n in [command.payload.name_vi, command.payload.name_en, *command.aliases] if n}
    if query not in names and not (command.resolution == 'create_distinct' and any(query in name for name in names)):
        raise HTTPException(422, 'Query must match the candidate name or an approved alias')
    model, output = MODELS[domain]
    if command.resolution == 'reuse':
        if str(command.existing_id) not in matches:
            raise HTTPException(409, 'Reuse target was not in the approved matches')
        record = await service.get(model, command.existing_id)
        if record.version_id != command.expected_existing_version:
            raise HTTPException(409, 'Reuse target changed')
    else:
        record = await service.create(model, command.payload)
        for alias in command.aliases:
            await service.session.execute(text(f'''INSERT INTO {domain}_aliases VALUES (:id,:alias)
                ON CONFLICT DO NOTHING'''), {'id':record.id,'alias':normalize_food_text(alias)})
    result = {'outcome':'reused' if command.resolution=='reuse' else 'created',
              'record':output.model_validate(record).model_dump(mode='json'), 'provenance':provenance}
    await service.session.execute(text('''INSERT INTO research_finalizations
        (owner_id,candidate_id,candidate_revision,digest,domain,command,result)
        VALUES (:owner,:candidate,:revision,:digest,:domain,CAST(:command AS jsonb),CAST(:result AS jsonb))'''),
        {**keys,'digest':request_digest,'domain':domain,'command':json.dumps(data),'result':json.dumps(result)})
    return result
