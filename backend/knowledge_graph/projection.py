"""Version-guarded projections. Every event is one atomic Neo4j transaction."""
import json
from datetime import datetime, timedelta, timezone

from .driver import value
from .models import ProjectionEvent
from .service import normalize

PROJECTION_VERSION = 1
NUTRIENTS = {'energy_kcal', 'protein_g', 'carbohydrate_g', 'fat_g', 'fiber_g'}
FOOD_FIELDS = NUTRIENTS | {'id', 'version_id', 'code', 'name_vi', 'name_en', 'category_vi', 'category_en',
                           'item_type', 'source_type', 'serving_size', 'serving_unit'}
FIELDS = {
    'User': {'id', 'is_active'},
    'Goal': {'id', 'version_id', 'title', 'description', 'goal_types', 'weight_kg_target',
             'targets', 'start_date', 'target_date', 'status'},
    'BodyMetric': {'id', 'version_id', 'recorded_at', 'weight_kg', 'height_cm', 'body_fat_pct', 'muscle_mass_kg'},
    'Food': FOOD_FIELDS,
    'Meal': NUTRIENTS | {'id', 'version_id', 'name', 'consumed_at', 'timezone', 'detail_status',
                         'replaces_id', 'nutrition_incomplete'},
    'Execution': {'run_id', 'session_id', 'session_generation', 'tool', 'status', 'duration_ms',
                  'error_code', 'template_id', 'template_version'},
    'Session': {'session_id', 'generation'},
}
ITEM_FIELDS = NUTRIENTS | {'id', 'version_id', 'position', 'food_id', 'quantity', 'unit', 'nutrition_incomplete'}
RELATIONS = {'Goal': 'HAS_GOAL', 'BodyMetric': 'HAS_MEASUREMENT', 'Meal': 'LOGGED'}


def sanitize(event):
    payload = event.payload
    data = {key: payload[key] for key in FIELDS[event.aggregate_type] if key in payload}
    if event.aggregate_type == 'Meal':
        data['items'] = []
        for source in payload.get('items', []):
            if source.get('is_active', True) is False:
                continue
            item = {key: source[key] for key in ITEM_FIELDS if key in source}
            item['food_snapshot'] = {key: val for key, val in source.get('food_snapshot', {}).items() if key in FOOD_FIELDS}
            data['items'].append(item)
    if event.aggregate_type == 'Execution':
        data['resource_refs'] = [
            {'kind': ref['kind'], 'source_id': str(ref['source_id'])}
            for ref in payload.get('resource_refs', [])
            if ref.get('kind') in {'Goal', 'BodyMetric', 'Meal', 'Food'} and ref.get('source_id')
        ][:20]
    return data


def utc_string(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def event_properties(event):
    data = sanitize(event)
    source_at = utc_string(event.occurred_at)
    fact = dict(kind=event.aggregate_type, source=event.source, source_id=event.aggregate_id,
                source_version=event.aggregate_version, source_at=source_at, data=data)
    props = dict(key=event.key, kind=event.aggregate_type, source=event.source, source_id=event.aggregate_id,
                 source_version=event.aggregate_version, owner_id=event.owner_id,
                 scope='SYSTEM' if event.aggregate_type == 'Food' and event.owner_id is None else 'PRIVATE',
                 projection_version=PROJECTION_VERSION, source_at=source_at,
                 projected_at=datetime.now(timezone.utc).isoformat(), deleted=event.operation == 'delete',
                 fact_json=json.dumps(fact, ensure_ascii=False, separators=(',', ':')),
                 search_text=normalize(' '.join(str(data.get(key, '')) for key in ('name', 'name_vi', 'name_en', 'title'))))
    props['business_at'] = utc_string(data.get('consumed_at') or data.get('recorded_at') or event.occurred_at)
    if event.aggregate_type == 'Goal':
        props['status'] = str(data.get('status', '')).upper()
    if event.aggregate_type == 'Execution':
        props.update({key: data.get(key) for key in ('session_id', 'session_generation', 'run_id', 'tool')})
        props['domain'] = tool_domain(data.get('tool', ''))
    return props, data


def tool_domain(name):
    if name == 'get_progress':
        return 'progress'
    if name.endswith('_goal'):
        return 'goals'
    for domain in ('meals', 'foods', 'metrics', 'goals'):
        if name.endswith('_' + domain):
            return domain
    return 'other'


class Projector:
    def __init__(self, driver, settings):
        self.driver, self.settings = driver, settings

    async def query(self, query, **params):
        async with self.driver.session(database=value(self.settings, 'NEO4J_DATABASE', 'neo4j')) as session:
            return await (await session.run(query, **params)).data()

    async def initialize(self):
        for label, prop in (('KGEntity', 'key'), ('KGOwner', 'key'), ('KGState', 'key'),
                            ('Agent', 'name'), ('Domain', 'name'), ('Tool', 'name'), ('TaskTemplate', 'id')):
            await self.query(f'CREATE CONSTRAINT kg_{label.lower()} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE')
        for name, expression in (('owner_kind', '(n.owner_id, n.kind)'), ('execution_owner', '(n.owner_id, n.source_at)')):
            label = 'Execution' if name == 'execution_owner' else 'KGEntity'
            await self.query(f'CREATE INDEX kg_{name} IF NOT EXISTS FOR (n:{label}) ON {expression}')
        await self.query('CREATE INDEX kg_food_scope IF NOT EXISTS FOR (n:Food) ON (n.scope)')
        await self.query("MERGE (s:KGState {key:'main'}) ON CREATE SET s.ready=false, s.generation=1")
        await self.seed_capabilities()

    async def seed_capabilities(self):
        # Registry is declarative and does not instantiate models or check keys.
        from agentic.tools.registry import REGISTRY
        rows = [dict(name=spec.name, domain=spec.domain, write=spec.write) for spec in REGISTRY.values()]
        await self.query("""
          MERGE (o:Agent {name:'orchestrator'}) MERGE (a:Agent {name:'tool_agent'})
          MERGE (r:Agent {name:'research_agent'})
          WITH o,a,r UNWIND $rows AS row
          MERGE (t:Tool {name:row.name}) SET t.domain=row.domain,t.write=row.write
          MERGE (d:Domain {name:row.domain})
          MERGE (t)-[:IN_DOMAIN]->(d) MERGE (a)-[:USES_TOOL]->(t)
          MERGE (a)-[:CAN_HANDLE]->(d) MERGE (o)-[:CAN_HANDLE]->(d)
          FOREACH (_ IN CASE WHEN row.domain IN ['foods','exercises'] THEN [1] ELSE [] END |
            MERGE (r)-[:CAN_HANDLE]->(d))
        """, rows=rows)
        await self.query("""
          MERGE (t:TaskTemplate {id:'progress.explicit_dates'})
          SET t.version=1,t.domain='progress',t.requires_tool='get_progress',t.enabled=true
          WITH t MATCH (tool:Tool {name:'get_progress'}) MERGE (t)-[:REQUIRES_TOOL]->(tool)
        """)

    async def apply(self, event: ProjectionEvent):
        if event.schema_version != 1 or event.payload.get('schema_version', 1) != 1:
            raise ValueError('Unsupported projection schema version')
        if event.aggregate_type != 'Food' and not event.owner_id:
            raise ValueError('Private projection requires owner_id')
        if event.source != ('agent' if event.aggregate_type in {'Execution', 'Session'} else 'backend'):
            raise ValueError('Projection source/type mismatch')
        if event.aggregate_type == 'Food' and event.payload.get('source_type') == 'CUSTOM' and not event.owner_id:
            raise ValueError('Custom catalog projection requires owner_id')
        async with self.driver.session(database=value(self.settings, 'NEO4J_DATABASE', 'neo4j')) as session:
            return await session.execute_write(self._apply, event)

    async def _apply(self, tx, event):
        # Every event for an owner first takes the same write lock. This makes
        # deleting an account race-safe even across separate outbox databases.
        if event.owner_id:
            result = await tx.run("""
                MERGE (o:KGOwner {key:$owner}) ON CREATE SET o.deleted=false, o.lock=0
                SET o.lock=o.lock+1 RETURN o.deleted AS deleted
            """, owner=event.owner_id)
            owner = await result.single()
            if owner['deleted'] and event.aggregate_type != 'User':
                return 'blocked_owner'
        result = await tx.run("""
            MERGE (n:KGEntity {key:$key}) ON CREATE SET n.source_version=0,n.lock=0
            SET n.lock=coalesce(n.lock,0)+1
            RETURN n.source_version AS version, n.session_generation AS generation
        """, key=event.key)
        previous = await result.single()
        if previous['version'] >= event.aggregate_version:
            return 'stale'
        props, data = event_properties(event)
        label = event.aggregate_type  # validated Literal, never request input
        if label == 'Session' and previous['generation'] is not None:
            props['session_generation'] = previous['generation']
        if event.aggregate_type == 'Execution':
            if data.get('status') not in {'succeeded', 'failed'}:
                raise ValueError('Only actual completed executions can be projected')
            if not data.get('session_id') or not data.get('run_id') or not isinstance(data.get('session_generation'), int):
                raise ValueError('Execution requires session/run/generation')
            session_key = 'agent:Session:' + data['session_id']
            record = await (await tx.run("""
                MERGE (s:KGEntity:Session {key:$key})
                ON CREATE SET s.source_version=0,s.deleted_through_generation=0,s.owner_id=$owner,s.kind='Session'
                SET s.lock=coalesce(s.lock,0)+1
                RETURN s.deleted_through_generation AS deleted_through, s.owner_id AS owner
            """, key=session_key, owner=event.owner_id)).single()
            if record['owner'] != event.owner_id or (record['deleted_through'] or 0) >= data['session_generation']:
                await tx.run('MATCH (n:KGEntity {key:$key}) SET n = $props', key=event.key,
                             props=self.tombstone(props))
                return 'blocked_session'
        else:
            session_key = None
        if event.operation == 'delete':
            await tx.run(f'MATCH (n:KGEntity {{key:$key}}) SET n:{label}, n = $props',
                         key=event.key, props=self.tombstone(props))
            await self._delete(tx, event)
            return 'deleted'
        # A deactivated account is terminal for this projection. Re-enabling one
        # requires rebuilding from source; an old event cannot restore its data.
        if event.aggregate_type == 'User' and owner['deleted']:
            return 'blocked_owner'
        await tx.run(f'MATCH (n:KGEntity {{key:$key}}) SET n:{label}, n = $props', key=event.key, props=props)
        if event.owner_id:
            await tx.run("""
                MERGE (u:KGEntity:User {key:$user_key})
                ON CREATE SET u.owner_id=$owner,u.source_version=0,u.kind='User',u.deleted=false
            """, user_key='backend:User:' + event.owner_id, owner=event.owner_id)
        if label in RELATIONS:
            await tx.run(f"MATCH (u:User {{key:$user_key}}),(n:{label} {{key:$key}}) MERGE (u)-[:{RELATIONS[label]}]->(n)",
                         user_key='backend:User:' + event.owner_id, key=event.key)
        if label == 'Meal':
            await self._meal(tx, event, data)
        if label == 'Execution':
            await self._execution(tx, event, data, session_key)
        if label in {'Goal', 'BodyMetric', 'Meal', 'Food'}:
            await tx.run("""
                MATCH (n:KGEntity {key:$key}), (e:Execution)
                WHERE $key IN e.target_keys AND (e.owner_id=n.owner_id OR (n:Food AND n.scope='SYSTEM'))
                MERGE (e)-[:TARGETS]->(n)
            """, key=event.key)
        if label == 'Food':
            await tx.run("""
                MATCH (f:Food {key:$key}), (i:MealItem {food_key:$key})
                WHERE i.owner_id=f.owner_id OR f.scope='SYSTEM'
                MERGE (i)-[:REFERS_TO]->(f)
            """, key=event.key)
        return 'applied'

    @staticmethod
    def tombstone(props):
        return {key: val for key, val in {**props, 'deleted': True}.items()
                if key in {'key','kind','source','source_id','source_version','owner_id','scope','deleted','source_at','projection_version','session_generation'}}

    async def _delete(self, tx, event):
        if event.aggregate_type == 'User':
            await tx.run('MATCH (o:KGOwner {key:$owner}) SET o.deleted=true', owner=event.owner_id)
            await tx.run('MATCH (n:KGEntity) WHERE n.owner_id=$owner AND n.key<>$key DETACH DELETE n',
                         owner=event.owner_id, key=event.key)
        elif event.aggregate_type == 'Session':
            generation = int(event.payload.get('generation', event.aggregate_version))
            await tx.run("""
                MATCH (s:Session {key:$key}) SET s.deleted_through_generation=$generation,
                    s.deleted=coalesce(s.session_generation,0)<=$generation
                WITH s MATCH (n:KGEntity)
                WHERE n.owner_id=$owner AND n.session_id=$session_id
                  AND coalesce(n.session_generation,0)<=$generation AND (n:Run OR n:Execution)
                DETACH DELETE n
            """, key=event.key, generation=generation, owner=event.owner_id, session_id=event.aggregate_id)
        elif event.aggregate_type == 'Meal':
            await tx.run('MATCH (m:Meal {key:$key})-[:HAS_ITEM]->(i:MealItem) DETACH DELETE i', key=event.key)

    async def _meal(self, tx, event, data):
        await tx.run('MATCH (m:Meal {key:$key})-[:HAS_ITEM]->(i:MealItem) DETACH DELETE i', key=event.key)
        rows = []
        for index, item in enumerate(data.get('items', [])):
            rows.append(dict(key=event.key + ':item:' + str(item.get('id', index)), owner_id=event.owner_id,
                             food_key='backend:Food:' + str(item.get('food_id', '')),
                             snapshot_json=json.dumps(item, ensure_ascii=False, separators=(',', ':')),
                             position=item.get('position', index)))
        await tx.run("""
            MATCH (m:Meal {key:$key}) UNWIND $rows AS row
            MERGE (i:KGEntity:MealItem {key:row.key})
            SET i.owner_id=row.owner_id,i.kind='MealItem',i.snapshot_json=row.snapshot_json,i.position=row.position,i.food_key=row.food_key
            MERGE (m)-[:HAS_ITEM]->(i)
            WITH i,row OPTIONAL MATCH (f:Food {key:row.food_key})
            WHERE f.owner_id=$owner OR f.scope='SYSTEM'
            FOREACH (_ IN CASE WHEN f IS NULL THEN [] ELSE [1] END | MERGE (i)-[:REFERS_TO]->(f))
        """, key=event.key, rows=rows, owner=event.owner_id)
        if data.get('replaces_id'):
            await tx.run("""
                MATCH (m:Meal {key:$key})
                MERGE (old:KGEntity:Meal {key:$previous})
                ON CREATE SET old.owner_id=$owner,old.source_version=0,old.deleted=true,old.kind='Meal'
                WITH m,old WHERE old.owner_id=$owner MERGE (m)-[:REPLACES]->(old)
            """, key=event.key, previous='backend:Meal:' + data['replaces_id'], owner=event.owner_id)

    async def _execution(self, tx, event, data, session_key):
        run_key = 'agent:Run:' + data['run_id']
        await tx.run("""
            MATCH (s:Session {key:$session_key}),(u:User {key:$user_key}),(e:Execution {key:$key})
            SET s.deleted=false,s.session_generation=$generation
            MERGE (u)-[:HAS_SESSION]->(s)
            MERGE (r:KGEntity:Run {key:$run_key})
            SET r.kind='Run',r.owner_id=$owner,r.session_id=$session_id,r.session_generation=$generation,r.source_at=$source_at
            MERGE (s)-[:HAS_RUN]->(r) MERGE (r)-[:HAS_EXECUTION]->(e)
            WITH e,r OPTIONAL MATCH (t:Tool {name:$tool})
            FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (e)-[:USES_TOOL]->(t))
        """, session_key=session_key,user_key='backend:User:' + event.owner_id,key=event.key,
                     run_key=run_key,owner=event.owner_id,session_id=data['session_id'],generation=data['session_generation'],
                     source_at=utc_string(event.occurred_at),tool=data.get('tool'))
        await tx.run("""
            MATCH (e:Execution {key:$key}) SET e.target_keys=[ref IN $refs | ref.key]
            WITH e UNWIND $refs AS ref
            MATCH (n:KGEntity {key:ref.key})
            WHERE n.owner_id=$owner OR (n:Food AND n.scope='SYSTEM')
            MERGE (e)-[:TARGETS]->(n)
        """,key=event.key,owner=event.owner_id,refs=[{'key':'backend:'+r['kind']+':'+r['source_id']} for r in data.get('resource_refs',[])])
        if data.get('template_id'):
            await tx.run("""
                MATCH (r:Run {key:$run_key}),(t:TaskTemplate {id:$template,version:$version})
                MERGE (r)-[:MATCHES_TEMPLATE]->(t)
            """,run_key=run_key,template=data['template_id'],version=data.get('template_version',1))

    async def prune(self):
        now = datetime.now(timezone.utc)
        for kinds, days in ((['Meal','BodyMetric'], value(self.settings,'KG_BUSINESS_RETENTION_DAYS',90)),
                            (['Execution','Run'], value(self.settings,'KG_MEMORY_RETENTION_DAYS',30))):
            await self.query("""
              MATCH (n:KGEntity) WHERE n.kind IN $kinds AND coalesce(n.business_at,n.source_at)<$cutoff
              OPTIONAL MATCH (n)-[:HAS_ITEM]->(item:MealItem)
              DETACH DELETE item
              SET n.fact_json=null,n.search_text=null,n.deleted=true
            """,kinds=kinds,cutoff=(now-timedelta(days=days)).isoformat())
        await self.query("MATCH (n:Goal) WHERE n.status<>'IN_PROGRESS' SET n.fact_json=null,n.deleted=true")
