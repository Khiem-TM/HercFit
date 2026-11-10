"""KG impact evaluation with the real models, backend and graph.

Run inside the agentic container (it reaches backend, Postgres and Neo4j):
    python -m agentic.evaluation.kg_eval seed
    python -m agentic.evaluation.kg_eval run --variants no_kg,kg --repeat 2 --out /tmp/kg_eval
    python -m agentic.evaluation.kg_eval retrieval --out /tmp/kg_retrieval

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
    parser.add_argument('command', choices=['seed', 'run', 'retrieval'])
    parser.add_argument('--variants', default='no_kg,kg', help='no_kg (ablation without the graph service) and/or kg')
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--groups', default='', help='comma-separated groups or case ids')
    parser.add_argument('--out', default='/tmp/kg_eval')
    args = parser.parse_args()
    if args.command == 'seed':
        asyncio.run(seed())
    elif args.command == 'retrieval':
        asyncio.run(retrieval(Path(args.out), set(filter(None, args.groups.split(',')))))
    else:
        asyncio.run(run(args.variants.split(','), args.repeat, Path(args.out), set(filter(None, args.groups.split(',')))))


if __name__ == '__main__':
    main()
