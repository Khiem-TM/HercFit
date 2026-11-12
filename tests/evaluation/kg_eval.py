"""KG impact evaluation with the real models, backend and graph.

Run from backend/ with PYTHONPATH=../tests, in a process that reaches backend, Postgres and Neo4j
(e.g. the agentic container with tests/ mounted):
    python -m evaluation.kg_eval seed
    python -m evaluation.kg_eval run --variants no_kg,kg --repeat 2 --out /tmp/kg_eval
    python -m evaluation.kg_eval retrieval --out /tmp/kg_retrieval

The knowledge graph has no runtime switch: it is always composed. The `no_kg` variant is an
ablation that composes the same app without a graph service (dependency injection), so both
variants share settings, models and prompts and differ only in the graph.

Scoring is rule-based: expected tool family, expected keywords and numbers in the
reply that are not present in any tool output, graph fact or the question.
The retrieval command needs no model: it checks whether the graph context the
agent would read already contains each expected answer (context recall).
"""
import argparse
import asyncio
import csv
import json
import re
import statistics
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import psycopg

from agentic.core.app.config import agent_settings
from core.security import create_access_token

EVAL_USER = UUID('01a20000-0000-7000-8000-00000000e7a1')
TZ = ZoneInfo('Asia/Ho_Chi_Minh')
CASES = Path(__file__).parent / 'datasets' / 'kg_cases.jsonl'
FOODS = {'pho': '01a15828-13a6-7e6f-8fdf-002c5c5eca16', 'com_suon': '01a15828-17a5-7d26-89a6-bbfa0cfea7a3',
         'banh_mi': '01a15828-137c-785b-8387-1cde815bb5e9', 'bun_cha': '01a15828-1387-772e-99e4-7345d9dad291'}
EXERCISES = {'bench': '01a1697c-75a5-778f-b0d0-fa7744d61090', 'run': '01a1697c-7651-74ee-9c09-f0312d26823f',
             'squat': '01a1697c-7605-7b63-9386-cfa42f2c9f17'}
TRAINING_PROFILE = {'experience_level': 'INTERMEDIATE', 'primary_focus': 'HYBRID', 'available_days': 4,
                    'session_minutes': 60, 'equipment': ['barbell', 'dumbbell']}


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text).lower().replace('đ', 'd'))
                   if unicodedata.category(c) != 'Mn')


def token():
    return create_access_token({'sub': str(EVAL_USER)}, expires_delta=timedelta(hours=6))


def day(offset, hour=12, minute=0):
    now = datetime.now(TZ)
    return (now + timedelta(days=offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def anchors():
    today = datetime.now(TZ).date()
    target = today + timedelta(days=60)
    return {'d0': today.isoformat(), 'd7': (today - timedelta(days=6)).isoformat(),
            'target_iso': target.isoformat(), 'target_vn': f'{target.day}/{target.month}',
            'target_vn0': target.strftime('%d/%m')}


def meal(name, offset, hour, food, grams):
    return '/meals', {'name': name, 'consumed_at': day(offset, hour).isoformat(),
                      'items': [{'food_id': FOODS[food], 'quantity': grams, 'unit': 'G'}]}


def bench(offset, weight):
    return '/trainings', {'name': 'Tập ngực', 'started_at': day(offset, 18).isoformat(), 'duration_seconds': 3600, 'session_rpe': 7,
                          'items': [{'exercise_id': EXERCISES['bench'], 'performance': {
                              'kind': 'STRENGTH', 'sets': [{'reps': 8, 'weight_kg': weight}] * 3}}]}


def running(name, offset, meters, seconds):
    return '/trainings', {'name': name, 'started_at': day(offset, 6).isoformat(), 'duration_seconds': seconds, 'session_rpe': 6,
                          'items': [{'exercise_id': EXERCISES['run'], 'performance': {
                              'kind': 'ENDURANCE', 'duration_seconds': seconds, 'distance_meters': meters}}]}


async def seed():
    """Two weeks of journal history. Idempotent: each tier is written once."""
    dsn = agent_settings.AGENT_DATABASE_URL.get_secret_value()
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute("""INSERT INTO users (id,email,fullname,email_verified) VALUES (%s,'kg-eval@hercfit.local','KG Eval',true)
                              ON CONFLICT (id) DO NOTHING""", (EVAL_USER,))
        await conn.execute('UPDATE users SET age=29 WHERE id=%s AND age IS DISTINCT FROM 29', (EVAL_USER,))
        meals = (await (await conn.execute('SELECT count(*) FROM meals WHERE user_id=%s', (EVAL_USER,))).fetchone())[0]
    today_breakfast = min(day(0, 7, 30), datetime.now(TZ) - timedelta(minutes=30))
    base = [
        ('/body-metrics', {'weight_kg': 74.0, 'height_cm': 172, 'recorded_at': day(-30, 7).isoformat()}),
        ('/body-metrics', {'weight_kg': 72.6, 'height_cm': 172, 'recorded_at': day(-10, 7).isoformat()}),
        ('/body-metrics', {'weight_kg': 71.8, 'height_cm': 172, 'recorded_at': day(-1, 7).isoformat()}),
        ('/goals/confirm', {'title': 'Giảm cân về 69kg', 'start_date': day(-30).date().isoformat(),
                            'target_date': day(60).date().isoformat(), 'goal_types': ['WEIGHT_LOSS'],
                            'description': 'Giảm từ 74kg về 69kg trong 3 tháng'}),
        meal('Bữa tối', -3, 19, 'bun_cha', 300),
        meal('Bữa trưa', -1, 12, 'com_suon', 250),
        meal('Bữa tối', -1, 19, 'pho', 500),
        ('/meals', {'name': 'Bữa sáng', 'consumed_at': today_breakfast.isoformat(),
                    'items': [{'food_id': FOODS['banh_mi'], 'quantity': 150, 'unit': 'G'}]}),
        running('Chạy sáng', -4, 5000, 1800),
        bench(-2, 60),
    ]
    history = [
        meal('Bữa trưa', -2, 12, 'pho', 500), meal('Bữa tối', -4, 19, 'pho', 450),
        meal('Bữa trưa', -5, 12, 'com_suon', 250), meal('Bữa sáng', -6, 7, 'banh_mi', 150),
        meal('Bữa tối', -8, 19, 'bun_cha', 300), meal('Bữa trưa', -9, 12, 'pho', 500),
        bench(-9, 55), bench(-6, 57.5), running('Chạy sáng', -7, 6000, 2100), running('Chạy dài', -12, 8000, 3000),
        ('/trainings', {'name': 'Tập chân', 'started_at': day(-10, 18).isoformat(), 'duration_seconds': 3600, 'session_rpe': 8,
                        'items': [{'exercise_id': EXERCISES['squat'], 'performance': {
                            'kind': 'STRENGTH', 'sets': [{'reps': 6, 'weight_kg': 80}] * 4}}]}),
    ]
    writes = (base if not meals else []) + (history if meals < 10 else [])
    async with httpx.AsyncClient(base_url=agent_settings.BACKEND_BASE_URL + '/api', timeout=30,
                                 headers={'Authorization': 'Bearer ' + token()}) as client:
        response = await client.put('/training/profile', json=TRAINING_PROFILE, headers={'Idempotency-Key': str(uuid4())})
        print('/training/profile', response.status_code)
        for path, body in writes:
            response = await client.post(path, json=body, headers={'Idempotency-Key': str(uuid4())})
            print(path, response.status_code, '' if response.is_success else response.text[:300])
            response.raise_for_status()
    await seed_turns()


# (router domain, tools that ran) per synthetic turn: 4× progress, 3× meal logging, 2× goal, 1× coaching.
HISTORY = [('progress', ['get_progress'])] * 4 + [('meals', ['create_meals'])] * 3 + \
          [('goals', ['current_goal'])] * 2 + [('coaching', ['get_training_insights'])]


async def seed_turns():
    """Conversation history journaled through the real store path, without model calls."""
    from agentic.services.memory.checkpoints import persistence
    async with persistence(agent_settings) as (store, _saver):
        async with store.pool.connection() as conn:
            existing = (await (await conn.execute('SELECT count(*) AS n FROM agent_turn_records WHERE user_id=%s',
                                                  (EVAL_USER,))).fetchone())['n']
        if existing >= len(HISTORY):
            print('turns: already seeded', existing)
            return
        for i, (domain, tools) in enumerate(HISTORY):
            session_id = f'kgeval-history-{i % 3}'
            async with store.session(session_id, str(EVAL_USER)) as session:
                generation = session['generation']
            run_id = str(uuid4())
            await store.bind(session_id, run_id)
            now = datetime.now(TZ).isoformat()
            await store.record_execution_state({
                'session_id': session_id, 'user_id': str(EVAL_USER), 'run_id': run_id, 'session_generation': generation,
                'status': 'completed', 'decision': {'intent': 'answer', 'domain': domain, 'action': 'answer'},
                'turn': {'run_id': run_id, 'intent': 'synthetic', 'domain': domain, 'action': 'tool'},
                'execution_records': [{'execution_id': str(uuid4()), 'tool': tool, 'status': 'succeeded', 'occurred_at': now,
                                       'resource_refs': []} for tool in tools]})
        print('turns:', len(HISTORY))


def numbers(text):
    text = re.sub(r'\d{4}-\d{2}-\d{2}|\d{1,2}[:h]\d{2}|\d{1,2}/\d{1,2}(/\d{2,4})?', ' ', text)
    return [float(n.replace(',', '.')) for n in re.findall(r'(?<![\w.])\d+(?:[.,]\d+)?', text)]


def grounded(value, sources):
    return value < 10 or any(abs(value - s) <= max(0.51, abs(s) * 0.01) for s in sources)


def score(case, response, values):
    outputs = values.get('tool_outputs') or []
    tools = [o.get('tool') for o in outputs if o.get('tool')]
    reply = normalize(response.reply)
    expected = case.get('tools')
    tool_ok = (not tools) if expected == [] else (expected is None or any(t in expected for t in tools))
    content_ok = all(any(normalize(k) in reply for k in group) for group in case.get('keywords', []))
    sources = set(numbers(json.dumps(outputs, ensure_ascii=False)))
    sources |= set(numbers(json.dumps(values.get('graph_context') or {}, ensure_ascii=False)))
    sources |= set(numbers(case['message']))
    # Simple derived values (differences, totals) are legitimate answers.
    base = sorted(sources)[:400]
    sources |= {round(a - b, 2) for a in base for b in base if a > b}
    ungrounded = [n for n in numbers(response.reply) if not grounded(n, sources)]
    return tools, tool_ok, content_ok, ungrounded


VARIANTS = ('no_kg', 'kg')


async def run_variant(variant, cases, repeat):
    from agentic.core.context import RequestContext, request_context
    from agentic.core.app.main import create_agentic_app
    from agentic.core.app.schemas.request import ChatRequest
    if variant not in VARIANTS:
        raise ValueError(f'Unknown variant {variant}; expected one of {VARIANTS}')
    # The ablation removes the graph service itself; nothing else differs between variants.
    app = create_agentic_app(agent_settings, graph_context_factory=(lambda _settings, _store: None) if variant == 'no_kg' else None)
    rows = []
    async with app.router.lifespan_context(app):
        # Like a long-running server, let any startup graph warm-up finish first.
        await asyncio.sleep(3)
        runtime, jwt = app.state.runtime, token()
        for attempt in range(repeat):
            for case in cases:
                mark = request_context.set(RequestContext(str(EVAL_USER), jwt, app.state.backend))
                started = perf_counter()
                try:
                    response = await runtime.chat(ChatRequest(message=case['message'], session_id='kgeval-' + uuid4().hex),
                                                  str(EVAL_USER))
                    values = (await runtime.state(response.run_id)).values
                except Exception as exc:
                    response, values = SimpleReply(f'ERROR {type(exc).__name__}'), {}
                finally:
                    request_context.reset(mark)
                elapsed = (perf_counter() - started) * 1000
                tools, tool_ok, content_ok, ungrounded = score(case, response, values)
                telemetry = values.get('telemetry') or {}
                retrieval = telemetry.get('retrieval') or {}
                rows.append({'variant': variant, 'attempt': attempt, 'id': case['id'], 'group': case['group'],
                             'status': getattr(response, 'status', 'error'), 'tool_ok': tool_ok, 'content_ok': content_ok,
                             'ungrounded': len(ungrounded), 'llm_calls': telemetry.get('llm_calls', 0),
                             'input_tokens': telemetry.get('input_tokens', 0), 'output_tokens': telemetry.get('output_tokens', 0),
                             'latency_ms': round(elapsed), 'kg_status': retrieval.get('status', '-'),
                             'kg_attempts': retrieval.get('attempts', 0),
                             'kg_ms': retrieval.get('duration_ms'), 'kg_facts': len((values.get('graph_context') or {}).get('facts', [])),
                             'tools': ' '.join(tools), 'reply': response.reply[:400].replace('\n', ' ')})
                row = rows[-1]
                print(f"[{variant}#{attempt}] {case['id']:<14} tool={row['tool_ok']!s:<5} content={row['content_ok']!s:<5} "
                      f"ungrounded={row['ungrounded']} llm={row['llm_calls']} tok={row['input_tokens']} "
                      f"{row['latency_ms']}ms kg={row['kg_status']}/{row['kg_facts']}", flush=True)
    return rows


class SimpleReply:
    def __init__(self, reply):
        self.reply, self.status = reply, 'error'


def summarize(rows):
    def pct(values):
        return f'{100 * sum(values) / len(values):.0f}%' if values else '-'

    def p(values, q):
        values = sorted(v for v in values if v is not None)
        return round(values[min(len(values) - 1, int(q * len(values)))]) if values else '-'
    lines = ['| variant | group | n | tool đúng | nội dung đúng | có số không căn cứ | LLM calls | input tokens | latency p50 | KG ok | KG p95 ms |',
             '|---|---|---|---|---|---|---|---|---|---|---|']
    groups = sorted({r['group'] for r in rows})
    for variant in dict.fromkeys(r['variant'] for r in rows):
        for group in [*groups, 'ALL']:
            sel = [r for r in rows if r['variant'] == variant and (group == 'ALL' or r['group'] == group)]
            if not sel:
                continue
            lines.append(f"| {variant} | {group} | {len(sel)} | {pct([r['tool_ok'] for r in sel])} | "
                         f"{pct([r['content_ok'] for r in sel])} | {pct([r['ungrounded'] > 0 for r in sel])} | "
                         f"{statistics.mean(r['llm_calls'] for r in sel):.2f} | {statistics.mean(r['input_tokens'] for r in sel):.0f} | "
                         f"{p([r['latency_ms'] for r in sel], .5)} | {pct([r['kg_status'] in {'ok', 'empty'} for r in sel])} | "
                         f"{p([r['kg_ms'] for r in sel if r['kg_status'] != '-'], .95)} |")
    return '\n'.join(lines)


def load_cases(only=()):
    context = anchors()
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    cases = [c for c in cases if not only or c['group'] in only or c['id'] in only]
    for case in cases:
        case['message'] = case['message'].format(**context)
        for field in ('keywords', 'context'):
            case[field] = [[k.format(**context) for k in group] for group in case.get(field, [])]
    return cases


async def retrieval(out, only):
    from agentic.services.routing import model_graph_context
    from agentic.services.memory.checkpoints import persistence
    from agentic.knowledge_graph.service import GraphContextService
    settings = agent_settings
    rows, contexts = [], []
    async with persistence(settings) as (store, _saver):
        service = GraphContextService(settings, store)
        if hasattr(service, 'warm_up'):
            await service.warm_up()
        for case in load_cases(only):
            started = perf_counter()
            context = await service.retrieve(str(EVAL_USER), 'kgeval-retrieval', case['message'])
            elapsed = (perf_counter() - started) * 1000
            state = {'run_id': 'eval', 'graph_context_run_id': 'eval', 'graph_context': context.model_dump(mode='json')}
            text = model_graph_context(state) or ''
            groups = case['context'] or case['keywords']
            recall = all(any(normalize(k) in normalize(text) for k in group) for group in groups) if groups else None
            rows.append({'id': case['id'], 'group': case['group'], 'status': context.status, 'recall': recall,
                         'bytes': len(text.encode()), 'lines': len(text.splitlines()), 'ms': round(elapsed, 1)})
            contexts.append(f"### {case['id']} — {case['message']}\nrecall={recall} status={context.status} {len(text.encode())}B\n\n{text or '(trống)'}\n")
            print(f"{case['id']:<18} recall={recall!s:<5} status={context.status:<8} {rows[-1]['bytes']:>5}B {elapsed:6.1f}ms", flush=True)
        await service.close()
    lines = ['| group | n | context recall | bytes TB | p95 ms |', '|---|---|---|---|---|']
    for group in [*sorted({r['group'] for r in rows}), 'ALL']:
        sel = [r for r in rows if group == 'ALL' or r['group'] == group]
        scored = [r['recall'] for r in sel if r['recall'] is not None]
        recall = f'{100 * sum(scored) / len(scored):.0f}% ({sum(scored)}/{len(scored)})' if scored else '-'
        p95 = sorted(r['ms'] for r in sel)[min(len(sel) - 1, int(.95 * len(sel)))]
        lines.append(f"| {group} | {len(sel)} | {recall} | {statistics.mean(r['bytes'] for r in sel):.0f} | {p95} |")
    out.mkdir(parents=True, exist_ok=True)
    (out / 'summary.md').write_text('\n'.join(lines) + '\n')
    (out / 'contexts.md').write_text('\n'.join(contexts))
    print('\n'.join(lines))


CONTEXT_CASES = Path(__file__).parent / 'datasets' / 'context_cases.jsonl'


async def seed_anchors():
    """Mốc theo ngày seed thật (bữa sáng 'hôm nay' lúc seed), để ca context không lệch khi seed đã cũ."""
    dsn = agent_settings.AGENT_DATABASE_URL.get_secret_value()
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        latest = (await (await conn.execute('SELECT max(consumed_at) FROM meals WHERE user_id=%s AND is_active',
                                            (EVAL_USER,))).fetchone())[0]
    if latest is None:
        raise SystemExit('eval user has no meals: run `kg_eval seed` first')
    s0 = latest.astimezone(TZ).date()
    marks = {}
    for k in range(0, 32):
        day = s0 - timedelta(days=k)
        marks[f's{k}'], marks[f's{k}_iso'], marks[f's{k}_month'] = day.strftime('%d/%m'), day.isoformat(), day.month
    return marks


def load_context_cases(marks, only=()):
    cases = [json.loads(line) for line in CONTEXT_CASES.read_text().splitlines() if line.strip()]
    cases = [c for c in cases if not only or c['group'] in only or c['id'] in only]
    for case in cases:
        case['message'] = case['message'].format(**marks)
        case['expect'] = [[k.format(**marks) for k in group] for group in case['expect']]
    return cases


async def context(out, only, generate=False, seeds=True, model=None):
    """Độ phủ của context graph (G_C) trên ca có đáp án chuẩn. Mặc định chỉ mẫu seed/đã học, không gọi model;
    --generate cho phép Context Agent sinh Cypher (tốn credit), --no-seeds đo riêng text-to-Cypher, --model ép Context
    Agent dùng đúng một model của provider mặc định (cùng khoá), không model dự phòng, để lỗi của nó không bị che."""
    from agentic.knowledge_graph.context import pipeline
    from agentic.knowledge_graph.context.graph import render
    from agentic.knowledge_graph.service import GraphContextService
    from agentic.observability.telemetry import active_metrics
    from agentic.services.memory.checkpoints import persistence
    models = None
    if generate:
        from agentic.core.llm import Models
        from agentic.observability.telemetry import MeasuredModels
        settings = agent_settings
        if model:
            # Vai trò decision của Context Agent chạy thẳng trên model này: không AGENT_MODELS, không FALLBACK_MODEL.
            settings = agent_settings.model_copy(update={'DECISION_MODEL': model, 'AGENT_MODELS': {},
                                                         'FALLBACK_MODEL': None})
        models = MeasuredModels(Models(settings))
    rows, dumps = [], []
    async with persistence(agent_settings) as (store, _saver):
        service = GraphContextService(agent_settings, store)
        await pipeline.warm_templates(service)
        for case in load_context_cases(await seed_anchors(), only):
            metrics = {}
            marker = active_metrics.set(metrics)
            try:
                graph = await pipeline.build(service, models, owner=str(EVAL_USER),
                                             session_id=case.get('session', 'kgeval-context'), question=case['message'],
                                             decision=case['decision'], generate=generate, seeds=seeds)
            finally:
                active_metrics.reset(marker)
            text = normalize('\n'.join(render(graph)))
            recall = all(any(normalize(k) in text for k in group) for group in case['expect'])
            rows.append({'id': case['id'], 'group': case['group'], 'recall': recall, 'status': graph.status,
                         'source': graph.source, 'template': graph.template, 'attempts': graph.attempts,
                         'error': graph.error, 'ms': graph.duration_ms, 'bytes': len('\n'.join(render(graph)).encode()),
                         'llm_calls': metrics.get('llm_calls', 0), 'input_tokens': metrics.get('input_tokens', 0),
                         'output_tokens': metrics.get('output_tokens', 0), 'model_ms': metrics.get('model_ms', 0)})
            dumps.append(f"### {case['id']} — {case['message']}\nrecall={recall} status={graph.status} "
                         f"source={graph.source}/{graph.template} error={graph.error}\n\n```cypher\n{graph.cypher}\n```\n\n"
                         + '\n'.join(render(graph)) + '\n')
            print(f"{case['id']:<22} recall={recall!s:<5} {graph.status:<9} {graph.source}/{graph.template} "
                  f"{graph.duration_ms:7.1f}ms {graph.error or ''}", flush=True)
        await service.close()
    lines = [f'model: {model or "default"} · generate={generate} · seeds={seeds}', '',
             '| group | n | recall | ok/empty | repaired | rejected | LLM calls | in tok TB | out tok TB | bytes TB '
             '| p50 ms | p95 ms |', '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for group in [*sorted({r['group'] for r in rows}), 'ALL']:
        sel = [r for r in rows if group == 'ALL' or r['group'] == group]
        ms = sorted(r['ms'] for r in sel)
        lines.append(f"| {group} | {len(sel)} | {sum(r['recall'] for r in sel)}/{len(sel)} | "
                     f"{sum(r['status'] in {'ok', 'empty'} for r in sel)} | "
                     f"{sum(r['attempts'] > 1 and r['status'] in {'ok', 'empty'} for r in sel)} | "
                     f"{sum(r['status'] == 'rejected' for r in sel)} | {sum(r['llm_calls'] for r in sel)} | "
                     f"{statistics.mean(r['input_tokens'] for r in sel):.0f} | "
                     f"{statistics.mean(r['output_tokens'] for r in sel):.0f} | "
                     f"{statistics.mean(r['bytes'] for r in sel):.0f} | {ms[len(ms) // 2]} | "
                     f"{ms[min(len(ms) - 1, int(.95 * len(ms)))]} |")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'rows.csv', 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out / 'summary.md').write_text('\n'.join(lines) + '\n')
    (out / 'contexts.md').write_text('\n'.join(dumps))
    print('\n'.join(lines))
    return 0 if all(r['recall'] for r in rows) else 1


# Truy vấn tấn công: mọi truy vấn phải bị từ chối. REWRITTEN chạy được nhưng chỉ sau khi validator gắn phạm vi người dùng.
ATTACKS = {
    'write': 'MATCH (m:Meal) DETACH DELETE m RETURN 1',
    'set': "MATCH (m:Meal) SET m.name = 'x' RETURN m",
    'merge': 'MERGE (m:Meal {name: $owner}) RETURN m',
    'call_procedure': 'CALL db.labels() YIELD label RETURN label',
    'load_csv': "LOAD CSV FROM 'http://x' AS row RETURN row",
    'union': 'MATCH (m:Meal) RETURN m.name UNION MATCH (n:Meal) RETURN n.name',
    'multi_statement': 'MATCH (m:Meal) RETURN m; MATCH (n) DETACH DELETE n',
    'unlabeled_node': 'MATCH (n) RETURN n LIMIT 5',
    'label_expression': 'MATCH (n:Meal|Training) RETURN n',
    'unknown_label': 'MATCH (n:Secret) RETURN n',
    'backtick_label': 'MATCH (m:`Meal`) RETURN m',
    'foreign_owner': "MATCH (m:Meal {owner_id: 'someone-else'}) RETURN m",
    'internal_owner_prop': 'MATCH (m:Meal) RETURN m.owner_id',
    'internal_fact_json': 'MATCH (m:Meal) RETURN m.fact_json',
    'properties_function': 'MATCH (m:Meal) RETURN properties(m)',
    'apoc_function': 'MATCH (m:Meal) RETURN apoc.convert.toJson(m)',
    'pattern_in_where': "MATCH (f:Food {scope:'SYSTEM'}) WHERE (f)<-[:REFERS_TO]-(:MealItem) RETURN f.name_vi",
    'pattern_comprehension': "MATCH (f:Food {scope:'SYSTEM'}) RETURN [(f)<-[:REFERS_TO]-(i:MealItem) | i.quantity]",
    'exists_subquery': "MATCH (f:Food {scope:'SYSTEM'}) WHERE EXISTS { MATCH (i:MealItem) } RETURN f",
    'count_subquery': "MATCH (f:Food {scope:'SYSTEM'}) RETURN COUNT { (i:MealItem)-[:REFERS_TO]->(f) }",
    'path_variable': 'MATCH p=(m:Meal)-[:HAS_ITEM]->(i:MealItem) RETURN p',
    'unbounded_hops': 'MATCH (r:Run)-[:NEXT*]->(x:Run) RETURN x',
    'quantified_path': 'MATCH ((a:Run)-[:NEXT]->(b:Run)){1,3} RETURN a',
    'untyped_relationship': 'MATCH (m:Meal)-->(x:MealItem) RETURN x',
    'wrong_endpoints': 'MATCH (m:Meal)-[:PERFORMED]->(x:Exercise) RETURN x',
    'scope_after_with': 'MATCH (m:Meal) WITH m.name AS n MATCH (x:MealItem) RETURN m',
    'generated_name': 'MATCH (_cg1:Meal) RETURN _cg1',
    'date_literal': "MATCH (m:Meal) WHERE m.local_date >= date('2026-09-01') RETURN m.name",
    'unknown_parameter': 'MATCH (m:Meal) WHERE m.name = $user RETURN m.name',
    'regex': "MATCH (m:Meal) WHERE m.name =~ '.*' RETURN m.name",
    'map_literal': 'MATCH (m:Meal) RETURN {a: m.name}',
    'big_limit': 'MATCH (m:Meal) RETURN m.name LIMIT 1000',
}
REWRITTEN = {
    # Đi vòng qua món dùng chung để đếm nhật ký của người khác: i2 cũng bị gắn owner.
    'foreign_items_via_food': 'MATCH (i1:MealItem)-[:REFERS_TO]->(f:Food)<-[:REFERS_TO]-(i2:MealItem) RETURN count(i2) AS n',
    # Biến ra khỏi phạm vi sau WITH rồi khai báo lại: nút mới phải được gắn owner lần nữa.
    'redeclared_after_with': 'MATCH (m:Meal) WITH count(m) AS c MATCH (m:Meal) RETURN c, m.name LIMIT 5',
    # Món riêng của người khác đọc thẳng từ catalog: bị giới hạn về dữ liệu hệ thống.
    'catalog_custom_foods': 'MATCH (f:Food) RETURN f LIMIT 50',
    'all_runs': 'MATCH (r:Run) RETURN r LIMIT 50',
}


async def safety(online=True):
    """Ba lớp chính sách của context graph: validator (offline), transaction chỉ đọc và lọc kết quả (cần Neo4j)."""
    from agentic.knowledge_graph.context.validator import CypherRejected, validate
    from agentic.knowledge_graph.schema import LABELS
    failures = []
    for name, query in ATTACKS.items():
        try:
            validate(query)
            failures.append(f'validator allowed {name}')
        except CypherRejected:
            pass
    for name, query in REWRITTEN.items():
        checked = validate(query).cypher
        for label, spec in LABELS.items():
            if spec.scope == 'private':
                for found in re.finditer(r'\((\w*):' + label + r'\b[^)]*\)', checked):
                    if 'owner_id: $owner' not in found.group(0):
                        failures.append(f'{name}: {found.group(0)} not scoped')
    print(f'validator: {len(ATTACKS)} attacks, {len(REWRITTEN)} rewrites checked')
    if online:
        from agentic.knowledge_graph.context.executor import _session, execute
        from agentic.knowledge_graph.context.policy import PolicyViolation
        from agentic.knowledge_graph.service import GraphContextService
        service = GraphContextService(agent_settings, None)
        owner = str(EVAL_USER)
        try:
            async with _session(service) as session:
                await (await session.run('CREATE (p:KGEvalProbe) RETURN p')).consume()
            failures.append('READ transaction accepted a write')
        except Exception as exc:  # noqa: BLE001
            if 'AccessMode' not in str(exc):
                failures.append(f'unexpected write error {type(exc).__name__}')
        try:
            await execute(service, 'MATCH (m:Meal) WHERE m.owner_id <> $owner AND m.deleted = false RETURN m LIMIT 1',
                          {'owner': owner}, owner=owner, sessions={}, timeout=2)
        except PolicyViolation:
            pass
        for name, query in REWRITTEN.items():
            try:
                await execute(service, validate(query).cypher, {'owner': owner, 'session_ids': ['\x00'],
                                                                'generations': {'\x00': 0}},
                              owner=owner, sessions={}, timeout=2)
            except PolicyViolation as exc:
                failures.append(f'{name}: rewritten query still returned {exc.code}')
        await service.close()
        print('online: read-only transaction, result policy and rewritten queries checked')
    for failure in failures:
        print('FAIL', failure)
    print('safety', 'PASS' if not failures else f'FAIL ({len(failures)})')
    return 2 if failures else 0


async def ryw():
    """Read-your-writes qua backend thật: ghi một số đo rồi hỏi ngay; context graph phải thấy nó hoặc báo chưa đồng bộ.
    Tạo JWT cho user eval và ghi vào database dev (xoá lại sau đó)."""
    from agentic.knowledge_graph.context import pipeline
    from agentic.knowledge_graph.context.graph import render
    from agentic.knowledge_graph.service import GraphContextService
    from agentic.services.memory.checkpoints import persistence
    weight = 70.3
    decision = {'intent': 'REVIEW_BODY', 'domain': 'metrics', 'context': {'focus': 'list'}}
    async with httpx.AsyncClient(base_url=agent_settings.BACKEND_BASE_URL + '/api', timeout=30,
                                 headers={'Authorization': 'Bearer ' + token()}) as client:
        created = await client.post('/body-metrics', json={'weight_kg': weight, 'recorded_at': datetime.now(TZ).isoformat()},
                                    headers={'Idempotency-Key': str(uuid4())})
        created.raise_for_status()
        started = perf_counter()
        async with persistence(agent_settings) as (store, _saver):
            service = GraphContextService(agent_settings, store)
            graph = await pipeline.build(service, None, owner=str(EVAL_USER), session_id='kgeval-ryw',
                                         question='Hôm nay tôi nặng bao nhiêu?', decision=decision, generate=False)
            await service.close()
        elapsed = (perf_counter() - started) * 1000
        record = created.json()
        await client.delete(f"/body-metrics/{record['id']}", params={'expected_version_id': record.get('version_id')},
                            headers={'Idempotency-Key': str(uuid4())})
    text = '\n'.join(render(graph))
    seen = f'{weight:g}' in text
    ok = seen or not graph.synced
    print(f'write→read {elapsed:.0f} ms · synced={graph.synced} · weight visible={seen} → {"PASS" if ok else "FAIL"}')
    return 0 if ok else 1


async def run(variants, repeat, out, only):
    cases = load_cases(only)
    rows = []
    for variant in variants:
        rows += await run_variant(variant, cases, repeat)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'rows.csv', 'w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    (out / 'summary.md').write_text(summary + '\n')
    print(summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['seed', 'run', 'retrieval', 'context', 'safety', 'ryw'])
    parser.add_argument('--variants', default='no_kg,kg', help='no_kg (ablation without the graph service) and/or kg')
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--groups', default='', help='comma-separated groups or case ids')
    parser.add_argument('--out', default='/tmp/kg_eval')
    parser.add_argument('--generate', action='store_true', help='context: let the Context Agent write Cypher (paid)')
    parser.add_argument('--no-seeds', action='store_true', help='context: skip hand-written templates (with --generate)')
    parser.add_argument('--offline', action='store_true', help='safety: validator only, no Neo4j (CI)')
    parser.add_argument('--model', default=None, help='context --generate: Context Agent model (same provider/key)')
    args = parser.parse_args()
    only = set(filter(None, args.groups.split(',')))
    if args.command == 'seed':
        asyncio.run(seed())
    elif args.command == 'context':
        raise SystemExit(asyncio.run(context(Path(args.out), only, generate=args.generate, seeds=not args.no_seeds,
                                             model=args.model)))
    elif args.command == 'safety':
        raise SystemExit(asyncio.run(safety(online=not args.offline)))
    elif args.command == 'ryw':
        raise SystemExit(asyncio.run(ryw()))
    elif args.command == 'retrieval':
        asyncio.run(retrieval(Path(args.out), only))
    else:
        asyncio.run(run(args.variants.split(','), args.repeat, Path(args.out), set(filter(None, args.groups.split(',')))))


if __name__ == '__main__':
    main()
