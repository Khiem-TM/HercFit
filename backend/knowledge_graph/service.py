"""Bounded retrieval with fixed Cypher and no model or driver retries."""
import asyncio
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from time import perf_counter

from .driver import create_driver, value
from .models import GraphContext

log = logging.getLogger(__name__)
PILOT_DOMAINS = {'meals', 'foods', 'metrics', 'goals', 'progress'}


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower().replace('đ', 'd'))
                   if unicodedata.category(c) != 'Mn')


def domain_for(message):
    text = normalize(message)
    for domain, pattern in (
        ('progress', r'\b(tien do|progress)\b'),
        ('meals', r'\b(bua an|da an|hom qua|an sang|an trua|an toi)\b'),
        ('foods', r'\b(mon an|thuc pham|calo|protein|dinh duong)\b'),
        ('metrics', r'\b(can nang|so do|chieu cao)\b'),
        ('goals', r'\b(muc tieu)\b'),
    ):
        if re.search(pattern, text):
            return domain
    return None


# No generated Cypher, variable-length paths, or unscoped traversals. All facts
# have an allowlisted JSON projection, including historical meal-item snapshots.
RETRIEVE = """
MATCH (state:KGState {key:'main'})
WHERE state.ready = true
CALL {
  WITH state
  CALL {
    MATCH (n:KGEntity {owner_id:$owner})
    WHERE n.kind IN $kinds AND n.deleted = false
    RETURN n
    UNION ALL
    MATCH (n:Food {scope:'SYSTEM'})
    WHERE 'Food' IN $kinds AND n.deleted = false
    RETURN n
  }
  WITH n WHERE (NOT n:Goal OR n.status = 'IN_PROGRESS')
    AND (NOT (n:Meal OR n:BodyMetric) OR n.business_at >= $business_cutoff)
  WITH n, CASE WHEN any(term IN $terms WHERE n.search_text CONTAINS term) THEN 1 ELSE 0 END AS score
  ORDER BY score DESC, n.business_at DESC, n.source_at DESC
  LIMIT $fact_limit
  RETURN collect(n.fact_json) AS facts
}
CALL {
  WITH state
  MATCH (n:Execution {owner_id:$owner})
  WHERE n.deleted = false AND n.source_at >= $memory_cutoff
    AND n.domain IN $domains AND n.session_id IN $session_ids
    AND n.session_generation = $generations[n.session_id]
  WITH n ORDER BY n.source_at DESC LIMIT $episode_limit
  RETURN collect(n.fact_json) AS episodes
}
CALL {
  WITH state
  MATCH (t:Tool)-[:IN_DOMAIN]->(d:Domain)
  WHERE d.name IN $domains
  WITH t ORDER BY t.name LIMIT 12
  RETURN collect({name:t.name, domain:t.domain, write:t.write}) AS capabilities
}
CALL {
  WITH state
  MATCH (t:TaskTemplate) WHERE t.domain IN $domains AND t.enabled = true
  RETURN collect({id:t.id, version:t.version, requires_tool:t.requires_tool}) AS templates
}
RETURN facts, episodes, capabilities, templates, state.projection_lag_ms AS projection_lag_ms
"""


class GraphContextService:
    def __init__(self, settings, store=None, *, driver=None):
        self.settings = settings
        self.store = store
        self.driver = driver

    async def close(self):
        if self.driver is not None:
            await self.driver.close()

    async def retrieve(self, authenticated_user_id, session_id, message, domain_hint=None, limits=None):
        if value(self.settings, 'KG_MODE', 'off') == 'off':
            return GraphContext(status='off')
        domain = domain_hint or domain_for(message)
        if domain not in PILOT_DOMAINS:
            return GraphContext(status='empty')
        start = perf_counter()
        try:
            deadline = min(float(value(self.settings, 'KG_RETRIEVAL_TIMEOUT_MS', 150)), 150) / 1000
            async with asyncio.timeout(deadline):
                result = await self._retrieve(str(authenticated_user_id), str(session_id), message, domain, limits or {})
        except TimeoutError:
            result = GraphContext(status='timeout')
        except Exception as exc:
            # Do not log user IDs, prompts, credentials, or driver exception text.
            log.warning('kg_retrieval_failed error_type=%s', type(exc).__name__)
            result = GraphContext(status='unavailable')
        log.info('kg_retrieval status=%s duration_ms=%.2f facts=%d episodes=%d',
                 result.status, (perf_counter() - start) * 1000, len(result.facts), len(result.episodes))
        return result

    async def _retrieve(self, owner, session_id, message, domain, limits):
        # Absence of a live source gate disables all episodic memory. A caller
        # must never rely on Neo4j alone to authorize deleted-session memory.
        gate = await self.store.kg_retrieval_gate(owner) if self.store is not None else {}
        if gate.get('blocked'):
            return GraphContext(status='blocked')
        generations = {str(k): int(v) for k, v in gate.get('session_generations', {}).items()
                       if str(k) not in set(gate.get('deleted_session_ids', []))}
        if self.driver is None:
            self.driver = create_driver(self.settings)
        now = datetime.now(timezone.utc)
        domains = [domain]
        if domain in {'meals', 'foods'}:
            domains = ['meals', 'foods']
        elif domain == 'progress':
            domains += ['meals', 'metrics', 'goals']
        kinds = {'meals': ['Meal', 'Food'], 'foods': ['Food'], 'metrics': ['BodyMetric'],
                 'goals': ['Goal'], 'progress': ['Goal', 'BodyMetric', 'Meal']}[domain]
        params = dict(
            owner=owner, session_ids=list(generations), generations=generations, domains=domains, kinds=kinds,
            terms=list(dict.fromkeys(re.findall(r'[a-z0-9]{3,}', normalize(message))))[:20],
            fact_limit=max(0, min(12, int(limits.get('facts', value(self.settings, 'KG_FACT_LIMIT', 12))))),
            episode_limit=max(0, min(3, int(limits.get('episodes', value(self.settings, 'KG_EPISODE_LIMIT', 3))))),
            business_cutoff=(now - timedelta(days=value(self.settings, 'KG_BUSINESS_RETENTION_DAYS', 90))).isoformat(),
            memory_cutoff=(now - timedelta(days=value(self.settings, 'KG_MEMORY_RETENTION_DAYS', 30))).isoformat(),
        )
        # session.run is an implicit transaction: it does not auto-retry reads.
        async with self.driver.session(database=value(self.settings, 'NEO4J_DATABASE', 'neo4j')) as session:
            record = await (await session.run(RETRIEVE, **params)).single()
        if record is None:
            return GraphContext(status='warming')
        data = dict(record)
        data['facts'] = [json.loads(item) for item in data['facts'] if item]
        data['episodes'] = [json.loads(item) for item in data['episodes'] if item]
        result = GraphContext(**data, status='ok' if data['facts'] or data['episodes'] else 'empty')
        for fact in result.facts:
            if fact.get('kind') == 'Meal' and any(item.get('nutrition_incomplete') for item in fact.get('data', {}).get('items', [])):
                result.missing_fields.append('Some historical meal nutrition is unknown; validate with backend.')
                break
        return bounded_context(result, min(1500, int(value(self.settings, 'KG_CONTEXT_TOKEN_BUDGET', 1500))))


def bounded_context(context, token_budget):
    # UTF-8 bytes are a conservative token upper bound, including Vietnamese;
    # never truncate JSON or a fact mid-value. Prefer concrete source facts.
    maximum = max(256, token_budget)
    def size():
        return len(context.model_dump_json().encode('utf-8'))
    for field in ('capabilities', 'templates', 'episodes', 'facts', 'missing_fields', 'conflicts'):
        values = getattr(context, field)
        while values and size() > maximum:
            values.pop()
    return context
