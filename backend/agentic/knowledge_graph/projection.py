"""Version-guarded projections. Every event is one atomic Neo4j transaction."""
import json
from datetime import datetime, timedelta, timezone

from .driver import value
from .intents import INTENTS, hub as intent_hub, label as intent_label
from .model import LOCAL, MODEL_VERSION, build_user_model, model_links
from .models import ProjectionEvent
from .service import normalize

PROJECTION_VERSION = 3
NUTRIENTS = {'energy_kcal', 'protein_g', 'carbohydrate_g', 'fat_g', 'fiber_g'}
FOOD_FIELDS = NUTRIENTS | {'id', 'version_id', 'code', 'name_vi', 'name_en', 'category_vi', 'category_en',
                           'item_type', 'source_type', 'serving_size', 'serving_unit'}
FIELDS = {
    'User': {'id', 'is_active', 'age', 'training_profile'},
    'Goal': {'id', 'version_id', 'title', 'description', 'goal_types', 'weight_kg_target',
             'targets', 'start_date', 'target_date', 'status'},
    'BodyMetric': {'id', 'version_id', 'recorded_at', 'weight_kg', 'height_cm', 'body_fat_pct', 'muscle_mass_kg'},
    'Food': FOOD_FIELDS,
    'Meal': NUTRIENTS | {'id', 'version_id', 'name', 'consumed_at', 'timezone', 'detail_status',
                         'replaces_id', 'nutrition_incomplete'},
    'Training': {'id', 'version_id', 'name', 'started_at', 'timezone', 'detail_status', 'discipline', 'duration_seconds',
                 'session_rpe', 'training_load', 'energy_kcal', 'calories_incomplete', 'replaces_id'},
    'Execution': {'run_id', 'session_id', 'session_generation', 'tool', 'status', 'duration_ms',
                  'error_code', 'template_id', 'template_version'},
    'Session': {'session_id', 'generation'},
    # A conversation turn: structured routing facts only, never message or reply text.
    'Run': {'run_id', 'session_id', 'session_generation', 'intent', 'domain', 'action', 'status', 'tools', 'occurred_at'},
}
PROFILE_FIELDS = {'experience_level', 'primary_focus', 'available_days', 'session_minutes', 'equipment'}
TURN_STATUSES = {'completed', 'needs_input', 'pending_confirmation', 'failed'}
MODEL_SOURCES = {'User', 'Goal', 'BodyMetric', 'Meal', 'Training'}
ITEM_FIELDS = NUTRIENTS | {'id', 'version_id', 'position', 'food_id', 'quantity', 'unit', 'nutrition_incomplete'}
TRAINING_ITEM_FIELDS = {'id', 'position', 'exercise_id', 'kind', 'duration_seconds', 'distance_meters', 'volume_kg', 'best_e1rm_kg', 'hard_sets', 'energy_kcal'}
EXERCISE_FIELDS = {'id', 'code', 'name_vi', 'name_en', 'kind', 'source_type'}
RELATIONS = {'Goal': 'HAS_GOAL', 'BodyMetric': 'HAS_MEASUREMENT', 'Meal': 'LOGGED', 'Training': 'TRAINED'}


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
    if event.aggregate_type == 'Training':
        data['items'] = [
            {**{key: source[key] for key in TRAINING_ITEM_FIELDS if key in source},
             'exercise': {key: val for key, val in source.get('exercise_snapshot', {}).items() if key in EXERCISE_FIELDS}}
            for source in payload.get('items', []) if source.get('is_active', True) is not False
        ]
    if event.aggregate_type == 'User':
        profile = payload.get('training_profile') or {}
        data['training_profile'] = {key: val for key, val in profile.items() if key in PROFILE_FIELDS} if isinstance(profile, dict) else {}
    if event.aggregate_type == 'Run':
        data['intent'] = data.get('intent') if data.get('intent') in INTENTS else 'CHAT'
        data['tools'] = [str(tool) for tool in data.get('tools') or []][:8]
    if event.aggregate_type in {'Execution', 'Run'}:
        data['resource_refs'] = [
            {'kind': ref['kind'], 'source_id': str(ref['source_id'])}
            for ref in payload.get('resource_refs', [])
            if ref.get('kind') in {'Goal', 'BodyMetric', 'Meal', 'Food', 'Training'} and ref.get('source_id')
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
                 search_text=search_text(data))
    props['business_at'] = utc_string(data.get('consumed_at') or data.get('recorded_at') or data.get('started_at')
                                      or data.get('occurred_at') or event.occurred_at)
    if event.aggregate_type == 'Goal':
        props['status'] = str(data.get('status', '')).upper()
    if event.aggregate_type == 'Execution':
        props.update({key: data.get(key) for key in ('session_id', 'session_generation', 'run_id', 'tool')})
        props['domain'] = tool_domain(data.get('tool', ''))
    if event.aggregate_type == 'Run':
        props.update({key: data.get(key) for key in ('session_id', 'session_generation', 'run_id', 'intent', 'domain', 'status')})
    return props, data


def search_text(data):
    # Meals and trainings are found by what was eaten or performed, not only by "Bữa tối".
    names = [data.get(key) for key in ('name', 'name_vi', 'name_en', 'title')]
    for item in data.get('items', []):
        snapshot = item.get('food_snapshot') or item.get('exercise') or {}
        names += [snapshot.get('name_vi'), snapshot.get('name_en')]
    return normalize(' '.join(str(name) for name in names if name))


def tool_domain(name):
    # The registry is the single source of tool domains, shared with routing and turns.
    from agentic.tools.registry import REGISTRY
    spec = REGISTRY.get(name)
    return spec.domain if spec else 'other'


class Projector:
    def __init__(self, driver, settings):
        self.driver, self.settings = driver, settings

    async def query(self, query, **params):
        async with self.driver.session(database=value(self.settings, 'NEO4J_DATABASE', 'neo4j')) as session:
            return await (await session.run(query, **params)).data()

    async def initialize(self):
        for label, prop in (('KGEntity', 'key'), ('KGOwner', 'key'), ('KGState', 'key'),
                            ('Agent', 'name'), ('Domain', 'name'), ('Tool', 'name'), ('TaskTemplate', 'id'), ('Intent', 'name')):
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
        if event.source != ('agent' if event.aggregate_type in {'Execution', 'Session', 'Run'} else 'backend'):
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
            RETURN coalesce(n.source_version, 0) AS version, n.session_generation AS generation
        """, key=event.key)
        previous = await result.single()
        if previous['version'] >= event.aggregate_version:
            return 'stale'
        props, data = event_properties(event)
        label = event.aggregate_type  # validated Literal, never request input
        if label == 'Session' and previous['generation'] is not None:
            props['session_generation'] = previous['generation']
        if event.aggregate_type in {'Execution', 'Run'}:
            statuses = TURN_STATUSES if event.aggregate_type == 'Run' else {'succeeded', 'failed'}
            if data.get('status') not in statuses:
                raise ValueError('Only actual completed executions and turns can be projected')
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
        if label == 'Training':
            await self._training(tx, event, data)
        if label == 'Execution':
            await self._execution(tx, event, data, session_key)
        if label == 'Run':
            await self._run(tx, event, data, session_key)
        if label in {'Goal', 'BodyMetric', 'Meal', 'Food', 'Training'}:
            await tx.run("""
                MATCH (n:KGEntity {key:$key}), (e:Execution)
                WHERE $key IN e.target_keys AND (e.owner_id=n.owner_id OR (n:Food AND n.scope='SYSTEM'))
                MERGE (e)-[:TARGETS]->(n)
            """, key=event.key)
        if label in {'Goal', 'BodyMetric', 'Meal', 'Training'}:
            # A turn may be journaled before the record it created is projected.
            await tx.run("""
                MATCH (n:KGEntity {key:$key}), (r:KGEntity {owner_id:$owner, kind:'Run'})
                WHERE $key IN coalesce(r.about_keys, [])
                MERGE (r)-[:ABOUT]->(n)
            """, key=event.key, owner=event.owner_id)
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
        elif event.aggregate_type == 'Training':
            await tx.run('MATCH (t:Training {key:$key})-[r:PERFORMED]->() DELETE r', key=event.key)

    async def _training(self, tx, event, data):
        """Training -[:PERFORMED]-> Exercise reference nodes carrying catalog identity only."""
        await tx.run('MATCH (t:Training {key:$key})-[r:PERFORMED]->() DELETE r', key=event.key)
        rows = []
        for item in data.get('items', []):
            exercise = item.get('exercise') or {}
            if not exercise.get('id'):
                continue
            system = exercise.get('source_type') == 'SYSTEM'
            fact = {'kind': 'Exercise', 'source': 'backend', 'data': {k: exercise[k] for k in ('name_vi', 'name_en', 'kind', 'code') if k in exercise}}
            rows.append(dict(key='backend:Exercise:' + str(exercise['id']), scope='SYSTEM' if system else 'PRIVATE',
                             owner_id=None if system else event.owner_id, position=item.get('position', 0),
                             fact_json=json.dumps(fact, ensure_ascii=False, separators=(',', ':'))))
        await tx.run("""
            MATCH (t:Training {key:$key}) UNWIND $rows AS row
            MERGE (x:KGEntity:Exercise {key:row.key})
            ON CREATE SET x.source_version=0
            SET x.kind='Exercise',x.scope=row.scope,x.owner_id=row.owner_id,x.fact_json=row.fact_json,x.deleted=false,x.source='backend'
            MERGE (t)-[p:PERFORMED]->(x) SET p.position=row.position
        """, key=event.key, rows=rows)
        if data.get('replaces_id'):
            await tx.run("""
                MATCH (t:Training {key:$key})
                MERGE (old:KGEntity:Training {key:$previous})
                ON CREATE SET old.owner_id=$owner,old.source_version=0,old.deleted=true,old.kind='Training'
                WITH t,old WHERE old.owner_id=$owner MERGE (t)-[:REPLACES]->(old)
            """, key=event.key, previous='backend:Training:' + data['replaces_id'], owner=event.owner_id)

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

    async def _run(self, tx, event, data, session_key):
        await tx.run("""
            MATCH (s:Session {key:$session_key}),(u:User {key:$user_key}),(r:Run {key:$key})
            SET s.deleted=false,s.session_generation=$generation,r.about_keys=$refs
            MERGE (u)-[:HAS_SESSION]->(s)
            MERGE (s)-[:HAS_RUN]->(r)
            WITH r
            OPTIONAL MATCH (r)-[old:HAS_INTENT|ABOUT]->()
            DELETE old
            WITH DISTINCT r
            MERGE (i:Intent {name:$intent}) SET i.label=$label, i.hub=$hub
            MERGE (r)-[:HAS_INTENT]->(i)
            WITH r UNWIND $refs AS ref
            MATCH (n:KGEntity {key:ref})
            WHERE n.owner_id=$owner OR (n:Food AND n.scope='SYSTEM')
            MERGE (r)-[:ABOUT]->(n)
        """, session_key=session_key, user_key='backend:User:' + event.owner_id, key=event.key, owner=event.owner_id,
                     generation=data['session_generation'], intent=data['intent'], label=intent_label(data['intent']),
                     hub=intent_hub(data['intent']),
                     refs=['backend:' + r['kind'] + ':' + r['source_id'] for r in data.get('resource_refs', [])])

    async def refresh_model(self, owner, now=None):
        """Recompute one owner's derived knowledge; idempotent and safe to repeat."""
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=value(self.settings, 'KG_BUSINESS_RETENTION_DAYS', 90))).isoformat()
        rows = await self.query("""
            MATCH (o:KGOwner {key:$owner}) WHERE coalesce(o.deleted, false) = false
            MATCH (u:KGEntity {key:$user_key}) WHERE coalesce(u.deleted, false) = false
            OPTIONAL MATCH (n:KGEntity {owner_id:$owner})
            WHERE n.kind IN ['User','Goal','BodyMetric','Meal','Training'] AND coalesce(n.deleted, false) = false
              AND n.fact_json IS NOT NULL AND (n.kind IN ['User','Goal'] OR coalesce(n.business_at, n.source_at) >= $cutoff)
            RETURN u.key AS user, collect(n.fact_json) AS facts
        """, owner=owner, user_key='backend:User:' + owner, cutoff=cutoff)
        if not rows:  # deleted or unknown owner; grouping by user keeps this empty
            return False
        # An owner whose history aged out still gets an (empty) model, so it is not re-selected every cycle.
        model = build_user_model([json.loads(fact) for fact in rows[0]['facts']], now)
        foods, exercises = model_links(model)
        await self.query("""
            MATCH (u:KGEntity {key:$user_key}) WHERE coalesce(u.deleted, false) = false
            MERGE (m:KGEntity {key:$key})
            SET m:UserModel, m.kind='UserModel', m.owner_id=$owner, m.deleted=false, m.model_json=$model,
                m.model_version=$version, m.computed_at=$now, m.today=$today, m.source_at=$now
            MERGE (u)-[:HAS_MODEL]->(m)
            WITH u
            OPTIONAL MATCH (u)-[old:FREQUENTLY_EATS|PRACTICES]->()
            DELETE old
            WITH DISTINCT u
            CALL (u) {
              UNWIND $foods AS food
              MATCH (f:KGEntity {key:food.key}) WHERE f.owner_id=$owner OR f.scope='SYSTEM'
              MERGE (u)-[r:FREQUENTLY_EATS]->(f) SET r.count=food.count, r.last_date=food.last_date
            }
            CALL (u) {
              UNWIND $exercises AS exercise
              MATCH (x:KGEntity {key:exercise.key}) WHERE x.owner_id=$owner OR x.scope='SYSTEM'
              MERGE (u)-[r:PRACTICES]->(x) SET r.sessions=exercise.sessions, r.last_date=exercise.last_date,
                r.best_e1rm_kg=exercise.best_e1rm_kg, r.distance_km=exercise.distance_km
            }
        """, user_key='backend:User:' + owner, key='model:' + owner, owner=owner, version=MODEL_VERSION,
                         model=json.dumps(model, ensure_ascii=False, separators=(',', ':')), now=now.isoformat(),
                         today=model['today'], foods=foods, exercises=exercises)
        return True

    async def stale_model_owners(self, limit=25, now=None):
        """Owners whose model is missing, outdated, or computed on an earlier local day."""
        now = now or datetime.now(timezone.utc)
        rows = await self.query("""
            MATCH (u:KGEntity:User) WHERE coalesce(u.deleted, false) = false AND u.owner_id IS NOT NULL
            OPTIONAL MATCH (u)-[:HAS_MODEL]->(m:UserModel)
            WITH u, m WHERE m IS NULL OR m.today < $today OR m.computed_at < $cutoff OR coalesce(m.model_version, 0) < $version
            RETURN u.owner_id AS owner ORDER BY coalesce(m.computed_at, '') LIMIT $limit
        """, today=now.astimezone(LOCAL).date().isoformat(), cutoff=(now - timedelta(hours=6)).isoformat(),
                                version=MODEL_VERSION, limit=limit)
        return [row['owner'] for row in rows]

    async def prune(self):
        now = datetime.now(timezone.utc)
        for kinds, days in ((['Meal','BodyMetric','Training'], value(self.settings,'KG_BUSINESS_RETENTION_DAYS',90)),
                            (['Execution','Run'], value(self.settings,'KG_MEMORY_RETENTION_DAYS',30))):
            await self.query("""
              MATCH (n:KGEntity) WHERE n.kind IN $kinds AND coalesce(n.business_at,n.source_at)<$cutoff
              OPTIONAL MATCH (n)-[:HAS_ITEM]->(item:MealItem)
              DETACH DELETE item
              SET n.fact_json=null,n.search_text=null,n.deleted=true
            """,kinds=kinds,cutoff=(now-timedelta(days=days)).isoformat())
        await self.query("MATCH (n:Goal) WHERE n.status<>'IN_PROGRESS' SET n.fact_json=null,n.deleted=true")
