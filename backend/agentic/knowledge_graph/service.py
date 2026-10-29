"""Bounded retrieval with fixed Cypher and no model or driver retries.

The agent reads a knowledge card: derived user-model sections chosen for the
request's domains first, then the most relevant recent records, then recent
conversation turns, all rendered as compact lines within a byte budget.
"""
from agentic.observability import observed, annotate
import asyncio
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from time import perf_counter
from zoneinfo import ZoneInfo

from .driver import create_driver, value
from .intents import label as intent_label
from .model import section_lines
from .models import GraphContext

log = logging.getLogger(__name__)
LOCAL = ZoneInfo('Asia/Ho_Chi_Minh')
# Routing domains with personal knowledge: fact kinds and user-model sections, by relevance.
KINDS = {'meals': ['Meal'], 'foods': ['Food', 'Meal'], 'metrics': ['BodyMetric'], 'goals': ['Goal'],
         'progress': ['Goal', 'BodyMetric', 'Meal'], 'trainings': ['Training'], 'coaching': ['Training'],
         'training_plans': ['Training'], 'profile': [], 'conversation': []}
SECTIONS = {
    'meals': ['nutrition', 'foods', 'goal'], 'foods': ['foods', 'nutrition'],
    'metrics': ['body', 'goal', 'profile'], 'goals': ['goal', 'body'],
    'progress': ['goal', 'nutrition', 'body', 'training'],
    'trainings': ['training', 'exercises', 'running', 'profile'], 'coaching': ['training', 'exercises', 'running', 'profile'],
    'training_plans': ['profile', 'training', 'exercises', 'goal'], 'profile': ['profile', 'body', 'goal'],
    'conversation': ['conversation'],
}
PILOT_DOMAINS = set(KINDS)
# Turns are journaled with the router domain of their first decision.
EPISODE_DOMAINS = {'meals': ['meals', 'foods'], 'foods': ['meals', 'foods'], 'coaching': ['coaching', 'trainings'],
                   'trainings': ['trainings', 'coaching'], 'progress': ['progress', 'meals', 'metrics', 'goals']}
DOMAIN_PATTERNS = (
    ('conversation', r'hay hoi|thuong hoi|da hoi|hoi ban|tro chuyen|cuoc hoi thoai|lich su chat'),
    ('profile', r'ho so|trinh do|thong tin ca nhan|\btuoi\b|\bbmi\b'),
    ('progress', r'tien do|progress|tong hop|bao cao'),
    ('training_plans', r'ke hoach tap|lich tap|giao an|chuong trinh tap|training plan'),
    ('trainings', r'buoi tap|bai tap|tai tap|tap luyen|\btap\b|\bchay\b|\bkm\b|training|workout|\bgym\b|day nguc|squat|deadlift|e1rm|ky luc'),
    ('metrics', r'can nang|\bcan\b|so do|chieu cao|\bweight\b'),
    ('goals', r'muc tieu|\bgoals?\b'),
    ('meals', r'\bbua\b|\bmon\b|\ban\b|\bmeals?\b|\bcalo|protein|dinh duong'),
    ('foods', r'thuc pham|\bfoods?\b'),
)
# Conversational words otherwise match names such as "Bữa tối" or "Quả ...".
STOPWORDS = {'toi', 'cua', 'ban', 'nay', 'qua', 'hom', 'kia', 'gan', 'nhat', 'bao', 'nhieu', 'khong', 'duoc',
             'voi', 'cho', 'xem', 'lan', 'nhung', 'the', 'nao', 'con', 'dang', 'sau', 'truoc', 'tuan', 'thang',
             'ngay', 'mot', 'cac', 'hay', 'giup', 'minh', 'trong', 'phu', 'hop'}
# Timed-out reads keep running to preserve pooled connections; past this many a
# slow graph is skipped instead of piling more queries onto the driver pool.
MAX_PENDING_READS = 4
STATUS = {'completed': 'hoàn tất', 'needs_input': 'chờ bổ sung', 'pending_confirmation': 'chờ xác nhận', 'failed': 'lỗi'}


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower().replace('đ', 'd'))
                   if unicodedata.category(c) != 'Mn')


def domains_for(message):
    """Every graph domain a message mentions; only a retrieval hint, never routing."""
    text = normalize(message)
    return [domain for domain, pattern in DOMAIN_PATTERNS if re.search(pattern, text)]


def domain_for(message):
    found = domains_for(message)
    return found[0] if found else None


def sections_for(domains):
    # Round-robin keeps each domain's most relevant section ahead of budget trimming.
    ranked = (section for group in zip_longest(*(SECTIONS.get(domain, []) for domain in domains)) for section in group if section)
    return list(dict.fromkeys(ranked))


# No generated Cypher, variable-length paths, or unscoped traversals. All facts
# have an allowlisted JSON projection, including historical meal-item snapshots.
RETRIEVE = """
MATCH (state:KGState {key:'main'})
WHERE state.ready = true
OPTIONAL MATCH (model:KGEntity {key:$model_key})
CALL () {
  CALL () {
    MATCH (n:KGEntity {owner_id:$owner})
    WHERE n.kind IN $kinds AND n.deleted = false
    RETURN n
    UNION ALL
    MATCH (n:Food {scope:'SYSTEM'})
    WHERE 'Food' IN $kinds AND n.deleted = false
    RETURN n
  }
  WITH n WHERE (NOT n:Goal OR n.status = 'IN_PROGRESS')
    AND (NOT (n:Meal OR n:BodyMetric OR n:Training) OR n.business_at >= $business_cutoff)
  WITH n, CASE WHEN any(term IN $terms WHERE n.search_text CONTAINS term) THEN 1 ELSE 0 END AS score
  ORDER BY score DESC, n.business_at DESC, n.source_at DESC
  WITH n.kind AS kind, collect(n.fact_json)[0..$per_kind] AS group
  UNWIND group AS fact
  WITH fact LIMIT $fact_limit
  RETURN collect(fact) AS facts
}
CALL () {
  MATCH (n:KGEntity {owner_id:$owner, kind:'Run'})
  WHERE n.deleted = false AND n.intent IS NOT NULL AND n.business_at >= $memory_cutoff
    AND ($any_domain OR n.domain IN $domains) AND n.session_id IN $session_ids
    AND n.session_generation = $generations[n.session_id]
  WITH n ORDER BY n.business_at DESC LIMIT $episode_limit
  RETURN collect(n.fact_json) AS episodes
}
CALL () {
  MATCH (n:KGEntity {owner_id:$owner, kind:'Run'})
  WHERE n.deleted = false AND n.intent IS NOT NULL AND n.business_at >= $memory_cutoff
    AND n.session_id IN $session_ids AND n.session_generation = $generations[n.session_id]
  WITH n.intent AS intent, count(*) AS turns, max(n.business_at) AS last_at
  ORDER BY turns DESC, last_at DESC LIMIT 6
  RETURN collect({intent: intent, turns: turns, last_at: last_at}) AS intents
}
RETURN facts, episodes, intents, state.projection_lag_ms AS projection_lag_ms,
       CASE WHEN model IS NULL OR coalesce(model.deleted, false) THEN null ELSE model.model_json END AS model
"""


class GraphContextService:
    def __init__(self, settings, store=None, *, driver=None):
        self.settings = settings
        self.store = store
        self.driver = driver
        self._background = set()

    def _settle(self, query):
        self._background.discard(query)
        if not query.cancelled():
            query.exception()  # retrieved: late failures are already degraded to 'timeout'

    async def close(self):
        for query in list(self._background):
            query.cancel()
        if self.driver is not None:
            await self.driver.close()

    async def warm_up(self):
        """Plan and run each domain query a few times at startup: cold reads (~0.15-0.9 s) exceed the cap."""
        if value(self.settings, 'KG_MODE', 'off') == 'off':
            return
        try:
            for _ in range(3):
                for domain in sorted(PILOT_DOMAINS):
                    await self._query('kg-warm-up', {}, [domain], 'warm up query', {})
        except Exception as exc:
            log.warning('kg_warm_up_failed error_type=%s', type(exc).__name__)

    @observed('kg.retrieve', 'retriever', capture=('message', 'domain_hint'))
    async def retrieve(self, authenticated_user_id, session_id, message, domain_hint=None, limits=None):
        if value(self.settings, 'KG_MODE', 'off') == 'off':
            return GraphContext(status='off')
        hints = [domain_hint] if isinstance(domain_hint, str) else list(domain_hint or domains_for(message))
        domains = [domain for domain in dict.fromkeys(hints) if domain in PILOT_DOMAINS]
        if not domains:
            return GraphContext(status='empty')
        if len(self._background) >= MAX_PENDING_READS:
            log.warning('kg_retrieval_skipped pending=%d', len(self._background))
            return GraphContext(status='timeout')
        start = perf_counter()
        query = asyncio.ensure_future(self._retrieve(str(authenticated_user_id), str(session_id), message, domains, limits or {}))
        self._background.add(query)
        query.add_done_callback(self._settle)
        try:
            deadline = min(float(value(self.settings, 'KG_RETRIEVAL_TIMEOUT_MS', 150)), 150) / 1000
            result = await asyncio.wait_for(asyncio.shield(query), deadline)
        except TimeoutError:
            # Stop waiting but let the read finish: cancelling mid-stream discards the
            # pooled connection, and reconnecting alone then exceeds the next deadline.
            result = GraphContext(status='timeout')
        except Exception as exc:
            # Do not log user IDs, prompts, credentials, or driver exception text.
            log.warning('kg_retrieval_failed error_type=%s', type(exc).__name__)
            result = GraphContext(status='unavailable')
        log.info('kg_retrieval status=%s duration_ms=%.2f facts=%d episodes=%d sections=%d',
                 result.status, (perf_counter() - start) * 1000, len(result.facts), len(result.episodes), len(result.sections))
        annotate(status=result.status, fact_count=len(result.facts), projection_lag_ms=result.projection_lag_ms)
        return result

    async def _retrieve(self, owner, session_id, message, domains, limits):
        # Absence of a live source gate disables all episodic memory. A caller
        # must never rely on Neo4j alone to authorize deleted-session memory.
        gate = await self.store.kg_retrieval_gate(owner) if self.store is not None else {}
        if gate.get('blocked'):
            return GraphContext(status='blocked')
        generations = {str(k): int(v) for k, v in gate.get('session_generations', {}).items()
                       if str(k) not in set(gate.get('deleted_session_ids', []))}
        record = await self._query(owner, generations, domains, message, limits)
        if record is None:
            return GraphContext(status='warming')
        data = dict(record)
        model = json.loads(data.pop('model', None) or 'null')
        data['facts'] = [json.loads(item) for item in data['facts'] if item]
        data['episodes'] = [json.loads(item) for item in data['episodes'] if item]
        result = GraphContext(**data, model=model, domains=domains, sections=sections_for(domains))
        result.status = 'ok' if render_lines(result) else 'empty'
        for fact in result.facts:
            if fact.get('kind') == 'Meal' and any(item.get('nutrition_incomplete') for item in fact.get('data', {}).get('items', [])):
                result.missing_fields.append('Some historical meal nutrition is unknown; validate with backend.')
                break
        return bounded_context(result, min(1500, int(value(self.settings, 'KG_CONTEXT_TOKEN_BUDGET', 1500))))

    async def _query(self, owner, generations, domains, message, limits):
        if self.driver is None:
            self.driver = create_driver(self.settings)
        now = datetime.now(timezone.utc)
        kinds = list(dict.fromkeys(kind for domain in domains for kind in KINDS[domain]))
        episode_domains = list(dict.fromkeys(item for domain in domains for item in EPISODE_DOMAINS.get(domain, [domain])))
        fact_limit = max(0, min(12, int(limits.get('facts', value(self.settings, 'KG_FACT_LIMIT', 12)))))
        terms = [term for term in dict.fromkeys(re.findall(r'[a-z0-9]{3,}', normalize(message))) if term not in STOPWORDS]
        params = dict(
            owner=owner, model_key='model:' + owner, session_ids=list(generations), generations=generations,
            domains=episode_domains, any_domain='conversation' in domains, kinds=kinds, terms=terms[:20],
            fact_limit=fact_limit, per_kind=max(2, fact_limit // max(1, len(kinds))),
            episode_limit=max(0, min(3, int(limits.get('episodes', value(self.settings, 'KG_EPISODE_LIMIT', 3))))),
            business_cutoff=(now - timedelta(days=value(self.settings, 'KG_BUSINESS_RETENTION_DAYS', 90))).isoformat(),
            memory_cutoff=(now - timedelta(days=value(self.settings, 'KG_MEMORY_RETENTION_DAYS', 30))).isoformat(),
        )
        # session.run is an implicit transaction: it does not auto-retry reads.
        async with self.driver.session(database=value(self.settings, 'NEO4J_DATABASE', 'neo4j')) as session:
            return await (await session.run(RETRIEVE, **params)).single()


def _local(value, with_time=True):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return str(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(LOCAL).strftime('%Y-%m-%d %H:%M' if with_time else '%Y-%m-%d')


def _amount(number, unit):
    if number is None:
        return None
    return f'{round(float(number), 1):g} {unit}'


def _join(*parts):
    return ' · '.join(str(part) for part in parts if part not in (None, '', []))


def _portion(item):
    food = item.get('food_snapshot') or {}
    unit = {'G': 'g', 'ML': 'ml', 'SERVING': ' phần'}.get(item.get('unit'), item.get('unit') or '')
    quantity = f"{round(float(item['quantity']), 1):g}{unit}" if item.get('quantity') is not None else None
    return ' '.join(filter(None, [food.get('name_vi') or food.get('name_en') or 'Món', quantity]))


def _exercise(item):
    exercise = item.get('exercise') or {}
    distance = _amount(item['distance_meters'] / 1000, 'km') if item.get('distance_meters') else None
    minutes = _amount(item['duration_seconds'] / 60, 'phút') if item.get('duration_seconds') else None
    details = _join(f"{item['hard_sets']} hiệp" if item.get('hard_sets') else None,
                    _amount(item.get('volume_kg'), 'kg volume'), _amount(item.get('best_e1rm_kg'), 'kg e1RM'),
                    distance, minutes)
    name = exercise.get('name_vi') or exercise.get('name_en') or 'Bài tập'
    return f'{name} ({details})' if details else name


def fact_line(fact):
    """One readable line per fact: IDs, versions and raw snapshots stay out of prompts."""
    data, kind = fact.get('data') or {}, fact.get('kind')
    if kind == 'Meal':
        return _join('Bữa ăn', _local(data.get('consumed_at')), data.get('name'),
                     ', '.join(_portion(item) for item in data.get('items', [])),
                     _amount(data.get('energy_kcal'), 'kcal'), _amount(data.get('protein_g'), 'g protein'))
    if kind == 'BodyMetric':
        return _join('Số đo', _local(data.get('recorded_at')), _amount(data.get('weight_kg'), 'kg'),
                     _amount(data.get('height_cm'), 'cm'), _amount(data.get('body_fat_pct'), '% mỡ'))
    if kind == 'Goal':
        return _join('Mục tiêu đang thực hiện', data.get('title'), data.get('description'),
                     f"từ {data.get('start_date')} đến {data.get('target_date') or 'chưa đặt'}",
                     _amount(data.get('weight_kg_target'), 'kg mục tiêu'))
    if kind == 'Training':
        return _join('Buổi tập', _local(data.get('started_at')), data.get('name'), data.get('discipline'),
                     _amount((data.get('duration_seconds') or 0) / 60 or None, 'phút'),
                     _amount(data.get('session_rpe'), 'RPE'), _amount(data.get('training_load'), 'tải sRPE'),
                     ', '.join(_exercise(item) for item in data.get('items', [])))
    if kind == 'Food':
        return _join('Thực phẩm', data.get('name_vi') or data.get('name_en'),
                     _amount(data.get('serving_size'), (data.get('serving_unit') or '').lower()),
                     _amount(data.get('energy_kcal'), 'kcal'), _amount(data.get('protein_g'), 'g protein'))
    if kind == 'Run':
        return _join('Lượt hội thoại', _local(data.get('occurred_at') or fact.get('source_at')),
                     intent_label(data.get('intent')), STATUS.get(data.get('status'), data.get('status')))
    if kind == 'Execution':
        return _join('Thao tác gần đây', _local(fact.get('source_at')), data.get('tool'), data.get('status'))
    return _join(kind, json.dumps({k: v for k, v in data.items() if not k.endswith('id')}, ensure_ascii=False))


def render_lines(context):
    data = context.model_dump() if isinstance(context, GraphContext) else context
    sections = section_lines(data.get('model'), data.get('sections') or [], data.get('intents') or [])
    # The goal section already states the active goal with its progress.
    covered = {'Goal'} if any(line.startswith('Mục tiêu:') for line in sections) else set()
    facts = [fact_line(fact) for fact in data.get('facts', []) if fact.get('kind') not in covered]
    episodes = [fact_line(fact) for fact in data.get('episodes', [])]
    notes = ['Lưu ý: ' + note for note in [*data.get('missing_fields', []), *data.get('conflicts', [])]]
    return sections + facts + episodes + notes


def bounded_context(context, token_budget):
    # UTF-8 bytes of the rendered prompt lines are a conservative token upper
    # bound, including Vietnamese. Whole lines only: derived sections are kept
    # longest, then concrete records, then conversation turns.
    maximum = max(256, token_budget)
    def size():
        return len('\n'.join(render_lines(context)).encode('utf-8'))
    for field in ('episodes', 'facts', 'missing_fields', 'conflicts', 'sections'):
        values = getattr(context, field)
        while values and size() > maximum:
            values.pop()
    return context
