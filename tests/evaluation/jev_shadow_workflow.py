"""Live off/shadow experiment on a compiled graph and isolated PostgreSQL ledger.

Business API/auth/UI, KG, Redis, retrieval and web search are frozen substitutes.
The LLM and Jev model calls are real. No business writes or enforce runs occur.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import uuid4, uuid5, NAMESPACE_URL

from evaluation.jev_eval import digest, measured_usage, percentile


SCOPE = ('Compiled LangGraph + real LLM/Jev + PostgreSQL ledger/research budgets; '
         'frozen business backend/RAG/Tavily; MemorySaver, no HTTP/auth/UI or production checkpoint validation')
FIXTURE_VERSION = 'jev-shadow-frozen-v2'
PROTOCOL_FIXTURE_VERSION = 'jev-shadow-protocol-posthoc-v1'
STAMP = '2026-10-24T00:00:00+00:00'


def workflow_cases():
    reads = [
        ('profile', 'Đọc hồ sơ cá nhân đã lưu của tôi.'),
        ('metrics', 'Đọc số đo cơ thể mới nhất đã lưu.'),
        ('goals', 'Đọc mục tiêu hiện tại đã lưu.'),
        ('meals', 'Đọc nhật ký ăn uống ngày 2026-10-20.'),
        ('trainings', 'Đọc nhật ký buổi tập ngày 2026-10-20.'),
        ('progress', 'Đọc báo cáo tiến độ từ 2026-10-20 đến 2026-10-21.'),
        ('foods', 'Tra catalog thức ăn EvalFood.'),
        ('exercises', 'Tra catalog bài tập EvalExercise.'),
        ('training_plans', 'Liệt kê các mẫu chương trình tập hiện có trong hệ thống.'),
    ]
    result = [{'case_id': 'read_' + domain, 'kind': 'read', 'fixture': 'reads',
               'expected_domain': domain, 'message': message} for domain, message in reads]
    for fixture in ('sufficient', 'missing', 'conflicting'):
        result.append({'case_id': 'research_' + fixture, 'kind': 'research', 'fixture': fixture,
                       'expected_domain': 'foods', 'message':
                       'Nghiên cứu nguồn công khai về EvalFood: theo các tài liệu, 100 g EvalFood chứa bao nhiêu protein? '
                       'Nếu nguồn thiếu hoặc bất đồng, hãy nói rõ; chỉ trả lời, không lưu dữ liệu.'})
    return result


def mode_order(repetition):
    return ('off', 'shadow') if repetition % 2 else ('shadow', 'off')


def validate_schedule(repeat, concurrency, pair_pause_seconds):
    if repeat < 3 or concurrency < 1:
        raise ValueError('At least three repetitions and positive concurrency are required')
    if not 0 <= pair_pause_seconds <= 60:
        raise ValueError('Pair pause must be between zero and sixty seconds')
    if pair_pause_seconds and concurrency != 1:
        raise ValueError('Pair pause requires concurrency=1 so it actually paces the schedule')


def protocol_research_cases():
    """Exploratory cases added after the main food matrix; never replace it."""
    return [{'case_id': 'protocol_' + variant, 'kind': 'research', 'fixture': variant,
             'fixture_version': PROTOCOL_FIXTURE_VERSION, 'posthoc_exploratory': True,
             'expected_domain': 'exercises', 'message':
             'Nghiên cứu nguồn công khai về bài tập giả lập EvalMoveAlpha. '
             'Theo tài liệu kiểm thử, EvalMoveAlpha tác động nhóm cơ nào và cần thiết bị gì? '
             'Chỉ trả lời hai ý này theo nguồn, không cần số hiệp hay mức tạ. '
             'Nếu tài liệu thiếu hoặc mâu thuẫn, hãy nói rõ; không tạo hoặc lưu dữ liệu.'}
            for variant in ('sufficient', 'missing', 'conflicting')]


def select_cases(*, protocol_research=False, case_ids=None, max_cases=None):
    cases = protocol_research_cases() if protocol_research else workflow_cases()
    if case_ids:
        if set(case_ids) - {case['case_id'] for case in cases}:
            raise ValueError('Unknown case ID for selected protocol')
        cases = [case for case in cases if case['case_id'] in case_ids]
    return cases[:max_cases] if max_cases else cases


def fixture_documents(case):
    variant = case['fixture']
    if case.get('fixture_version') == PROTOCOL_FIXTURE_VERSION:
        if variant == 'missing':
            contents = ['This is a frozen synthetic manual for EvalMoveAlpha. '
                        'Tài liệu chỉ ghi tên EvalMoveAlpha, không cung cấp nhóm cơ hoặc thiết bị.']
        else:
            contents = ['Approved synthetic manufacturer exercise manual, revision 1: EvalMoveAlpha. '
                        'Primary muscle group: CHEST (ngực). Required equipment: DUMBBELL (tạ đơn). '
                        'Hai dữ kiện này mô tả bài tập kiểm thử EvalMoveAlpha; tài liệu không đưa ra lời khuyên cá nhân.']
            if variant == 'conflicting':
                contents.append('Another approved synthetic manufacturer manual, revision 1, for the same EvalMoveAlpha: '
                                'Primary muscle group: BACK (lưng). Required equipment: BARBELL (tạ đòn). '
                                'Không có thông tin về phiên bản mới hơn hoặc nguồn ưu tiên để giải quyết bất đồng.')
        return [{'id': 'protocol-fixture-kb-' + str(index), 'content': content,
                 'title': 'Approved synthetic exercise manufacturer manual ' + str(index),
                 'version': 1, 'source_url': 'https://example.org/frozen/evalmovealpha-' + str(index), 'page': 1}
                for index, content in enumerate(contents, 1)]
    if variant == 'missing':
        contents = ['Tài liệu kiểm thử tổng hợp chỉ ghi tên EvalFood. Không cung cấp thành phần hoặc lượng protein.']
    else:
        contents = ['Synthetic manufacturer label for EvalFood: serving size 100 g, protein 10 g. '
                    'Nhãn nhà sản xuất dùng cho kiểm thử: 100 g EvalFood chứa 10 g protein.']
        if variant == 'conflicting':
            contents.append('Another synthetic manufacturer label for the same EvalFood variant: '
                            'serving size 100 g, protein 20 g. Không có thông tin để xác định nhãn nào đúng.')
    return [{'id': 'fixture-kb-' + str(index), 'content': content,
             'title': 'Approved synthetic manufacturer label ' + str(index), 'version': 1,
             'source_url': 'https://example.org/frozen/evalfood-' + str(index), 'page': 1}
            for index, content in enumerate(contents, 1)]


class FrozenBackend:
    """Typed, immutable synthetic read responses; every mutation is rejected."""
    def __init__(self, case, user_id):
        self.case, self.user_id = deepcopy(case), user_id
        self.calls, self.writes_blocked = [], 0

    def entity(self, tag):
        return {'id': str(uuid5(NAMESPACE_URL, 'jev-shadow-fixture:' + tag)),
                'created_at': STAMP, 'updated_at': STAMP, 'version_id': 1, 'is_active': True}

    def responses(self):
        profile = {**self.entity('profile'), 'id': self.user_id, 'email': 'jev.fixture@example.org',
                   'fullname': 'Synthetic Shadow Fixture', 'email_verified': True,
                   'last_login_at': None, 'is_onboarding': True, 'personal_info': {}, 'age': 30}
        metric = {**self.entity('metric'), 'user_id': self.user_id, 'weight_kg': 70,
                  'height_cm': 175, 'recorded_at': STAMP}
        goal = {**self.entity('goal'), 'user_id': self.user_id, 'title': 'Mục tiêu fixture',
                'start_date': '2026-10-01', 'target_date': '2026-12-01', 'status': 'IN_PROGRESS',
                'goal_types': ['weight'], 'targets': {'weight_kg': {'operator': 'eq', 'value': 70, 'unit': 'kg', 'baseline': 72}}}
        food = {**self.entity('food'), 'code': 'eval_food', 'name_vi': 'EvalFood',
                'source_type': 'SYSTEM', 'owner_user_id': None, 'serving_size': 100,
                'protein_g': 10, 'energy_kcal': 100}
        exercise = {**self.entity('exercise'), 'code': 'eval_exercise', 'name_vi': 'EvalExercise',
                    'source_type': 'SYSTEM', 'owner_user_id': None, 'kind': 'STRENGTH',
                    'configuration': {'kind': 'STRENGTH'}, 'muscle_groups': ['CHEST']}
        return {'get_profile': profile, 'latest_metrics': metric, 'list_metrics': [metric],
                'current_goal': goal, 'list_goals': [goal], 'list_meals': [], 'list_trainings': [],
                'list_foods': [food], 'list_exercises': [exercise], 'list_training_templates': [],
                'get_progress': {'timezone': 'Asia/Ho_Chi_Minh', 'start_date': '2026-10-20',
                                 'end_date': '2026-10-21', 'days': []}}

    async def call(self, name, args, token, **kwargs):
        from pydantic import TypeAdapter
        from agentic.tools.integrations.backend_client import BackendError
        from agentic.tools.registry import REGISTRY
        spec = REGISTRY[name]
        self.calls.append({'tool': name, 'arguments': deepcopy(args), 'write': spec.write})
        if spec.write:
            self.writes_blocked += 1
            raise BackendError(403, 'Synthetic fixture forbids business mutations')
        mapping = self.responses()
        if name.startswith('resolve_'):
            return {'status': 'EXACT', 'record': mapping['list_' + spec.domain][0],
                    'matches': mapping['list_' + spec.domain], 'fingerprint': '0' * 64}
        if name in mapping:
            value = mapping[name]
        elif name.startswith('get_') and ('list_' + spec.domain) in mapping:
            values = mapping['list_' + spec.domain]
            if not values:
                raise BackendError(404, 'No synthetic record')
            value = values[0]
        else:
            raise BackendError(404, 'No synthetic fixture for requested read')
        return TypeAdapter(spec.output).dump_python(TypeAdapter(spec.output).validate_python(deepcopy(value)), mode='json')

    async def request(self, method, path, token, **kwargs):
        self.calls.append({'method': method, 'path': path, 'write': False})
        if method == 'POST' and path == '/api/knowledge/search':
            return {'chunks': deepcopy(fixture_documents(self.case))}
        raise ValueError('Unsupported synthetic HTTP operation')


class FrozenTavily:
    def __init__(self, case):
        self.case, self.calls = deepcopy(case), []

    async def search(self, query, *, reserve=None, **kwargs):
        self.calls.append({'operation': 'search'})
        if reserve:
            await reserve('search'); await reserve('web')
        return [{'url': row['source_url'], 'title': row['title'],
                 'content': row['content'] + (' Frozen synthetic passage.' * 30)}
                for row in fixture_documents(self.case)]

    async def extract(self, urls, *, reserve=None):
        self.calls.append({'operation': 'extract'})
        if urls and reserve:
            await reserve('web')
        return []

    async def search_images(self, query, *, limit=4, reserve=None):
        self.calls.append({'operation': 'images'})
        if reserve:
            await reserve('search'); await reserve('web')
        return []


@asynccontextmanager
async def isolated_store(database_url, concurrency):
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool
    from agentic.services.memory.store import Store
    schema = 'jev_shadow_' + uuid4().hex
    admin = await psycopg.AsyncConnection.connect(database_url, autocommit=True)
    await admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    pool = AsyncConnectionPool(database_url, min_size=1, max_size=max(4, concurrency * 3), open=False,
                               kwargs={'autocommit': True, 'row_factory': dict_row, 'options': '-csearch_path=' + schema})
    try:
        await pool.open(wait=True)
        store = Store(pool)
        migrations = Path(__file__).resolve().parents[2] / 'backend' / 'agentic' / 'migrations'
        async with pool.connection() as conn:
            for path in sorted(migrations.glob('[0-9]*_*.sql')):
                await conn.execute(path.read_text())
                await conn.execute('INSERT INTO agent_schema_version VALUES (%s) ON CONFLICT DO NOTHING',
                                   (int(path.name.split('_', 1)[0]),))
        await store.ready()
        yield store
    finally:
        await pool.close()
        await admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
        await admin.close()


def summarize(rows):
    versions = sorted({row.get('fixture_version', FIXTURE_VERSION) for row in rows})
    result = {'scope': SCOPE, 'fixture_version': versions[0] if len(versions) == 1 else versions,
              'posthoc_exploratory': any(row.get('posthoc_exploratory', False) for row in rows),
              'rows': len(rows), 'modes': {}}
    for mode in ('off', 'shadow'):
        selected = [row for row in rows if row['mode'] == mode]
        usage = [row.get('usage', {}) for row in selected]
        def total(field):
            values = [row.get(field) for row in usage]
            return sum(values) if selected and all(value is not None for value in values) else None
        result['modes'][mode] = {
            'runs': len(selected), 'statuses': dict(Counter(row.get('status', 'error') for row in selected)),
            'latency_mean_ms': mean(row['latency_ms'] for row in selected) if selected else None,
            'latency_p95_ms': percentile([row['latency_ms'] for row in selected], .95),
            'all_in_tokens': total('tokens'), 'all_in_cost': total('cost'),
            'llm_calls': sum(row.get('telemetry', {}).get('llm_calls', 0) for row in selected),
            'jev_shadow_calls': sum(row.get('telemetry', {}).get('jev_shadow_calls', 0) for row in selected),
            'routing_gate_accepted': sum(bool(event.get('accepted')) for row in selected for event in row.get('jev_events', []) if event.get('phase') == 'routing'),
            'mutation_calls': sum(row.get('checks', {}).get('business_mutations', 0) for row in selected),
            'routing_matches': sum(row.get('actual_domain') == row.get('expected_domain') for row in selected if row.get('kind') == 'read'),
            'research_statuses': dict(Counter(row.get('research_result', {}).get('status', 'not_reached') for row in selected if row.get('kind') == 'research')),
        }
    result['limitations'] = ['No human-reviewed answer quality labels', 'No production promotion decision',
                            'Shadow adds model calls but cannot save routing calls or change research decisions',
                            'LLM nondeterminism and provider caches can change paired responses',
                            'Unknown prices remain unknown; all-in totals include shadow usage']
    return result


async def run(args):
    if not args.allow_live:
        raise ValueError('--allow-live is required')
    validate_schedule(args.repeat, args.concurrency, args.pair_pause_seconds)
    database_url = args.database_url or os.environ.get('JEV_SHADOW_DATABASE_URL')
    if not database_url:
        raise ValueError('Set JEV_SHADOW_DATABASE_URL to an isolated PostgreSQL database')
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import MemorySaver
    from agentic.core.app.config import agent_settings
    from agentic.core.context import RequestContext, request_context
    from agentic.core.llm import Models
    from agentic.services.jev import JevService
    from agentic.tools.integrations.jev import JevClient
    from agentic.agents.workflow import build_workflow
    settings = agent_settings.model_copy(update={'RAG_ENABLED': True,
                                                 'KG_MODE': 'off', 'FAST_READ_ENABLED': False,
                                                 'SESSION_MEMORY_MODE': 'off',
                                                 'RUN_TIMEOUT_SECONDS': 90, 'MAX_GRAPH_STEPS': 20,
                                                 'MAX_TOOL_CALLS': 6})
    settings.check_jev()
    cases = select_cases(protocol_research=args.protocol_research, case_ids=args.case_id, max_cases=args.max_cases)
    if not cases:
        raise ValueError('No selected cases')
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    semaphore = asyncio.Semaphore(args.concurrency)
    with output.with_suffix('.runs.jsonl').open('x') as runs:
        async with isolated_store(database_url, args.concurrency) as store:
            async def pair(case, repetition):
                async with semaphore:
                    owner = str(uuid4())
                    for mode in mode_order(repetition):
                        config = settings.model_copy(update={'JEV_MODE': mode})
                        backend, tavily = FrozenBackend(case, owner), FrozenTavily(case)
                        models, client = Models(config), JevClient(config)
                        service = JevService(client, store, config)
                        graph = build_workflow(models, store, MemorySaver(), tavily, config, jev=service)
                        run_id, session_id = str(uuid4()), 'jev-shadow-' + uuid4().hex
                        async with store.pool.connection() as conn:
                            await conn.execute('INSERT INTO agent_sessions(session_id,user_id) VALUES (%s,%s)', (session_id, owner))
                        initial = {'run_id': run_id, 'session_id': session_id, 'user_id': owner,
                                   'messages': [HumanMessage(content=case['message'])], 'tool_outputs': [],
                                   'tool_count': 0, 'research_count': 0, 'status': 'running', 'turn': None,
                                   'jev_events': [], 'jev_rejections': {}, 'pending_action': None}
                        marker = request_context.set(RequestContext(owner, 'synthetic-fixture-token', backend,
                                                                     ('Synthetic Shadow Fixture', 'jev.fixture@example.org')))
                        started = perf_counter()
                        row = {**case, 'repeat': repetition, 'mode': mode,
                               'fixture_version': case.get('fixture_version', FIXTURE_VERSION),
                               'fixture_fingerprint': digest({'case': case, 'documents': fixture_documents(case)})}
                        try:
                            async with asyncio.timeout(config.RUN_TIMEOUT_SECONDS):
                                state = await graph.ainvoke(initial, {'configurable': {'thread_id': run_id},
                                                                    'recursion_limit': config.MAX_GRAPH_STEPS})
                            telemetry = state.get('telemetry', {})
                            row.update(status=state.get('status'), actual_domain=(state.get('turn') or {}).get('domain'),
                                       reply=state.get('reply'), research_result=state.get('research_result') or {},
                                       usage=measured_usage(telemetry), telemetry=telemetry,
                                       jev_events=state.get('jev_events', []), research_usage=state.get('research_usage', {}),
                                       checks={'reply_present': bool(state.get('reply')),
                                               'expected_domain_match': (state.get('turn') or {}).get('domain') == case['expected_domain'],
                                               'business_mutations': sum(bool(call.get('write')) for call in backend.calls),
                                               'writes_blocked': backend.writes_blocked,
                                               'pending_action': bool(state.get('pending_action')),
                                               'read_tool_observed': bool(state.get('tool_outputs')),
                                               'read_tools_ok': all(item.get('ok') for item in state.get('tool_outputs', []))},
                                       backend_tools=[call['tool'] for call in backend.calls if 'tool' in call],
                                       frozen_search_calls=len(tavily.calls))
                        except Exception as exc:
                            row.update(status='error', error_type=type(exc).__name__, usage={'tokens': None, 'cost': None})
                        finally:
                            request_context.reset(marker)
                            await client.close()
                        row['latency_ms'] = round((perf_counter() - started) * 1000, 3)
                        # Run IDs, UUIDs, credentials and source passages are not necessary for the report.
                        row.get('telemetry', {}).pop('run_id', None)
                        rows.append(row)
                        runs.write(json.dumps(row, ensure_ascii=False, default=str) + '\n'); runs.flush()
                        print(json.dumps({'case': case['case_id'], 'repeat': repetition, 'mode': mode,
                                          'status': row['status'], 'latency_ms': row['latency_ms']}), flush=True)
                    # This scheduling intervention is outside each timed run.
                    # Concurrency=1 is required so another pair cannot bypass it.
                    if args.pair_pause_seconds:
                        await asyncio.sleep(args.pair_pause_seconds)
            for repetition in range(1, args.repeat + 1):
                await asyncio.gather(*(pair(case, repetition) for case in cases))
            async with store.pool.connection() as conn:
                ledger = await (await conn.execute('SELECT mode,sum(routing) AS routing,sum(research) AS research,count(*) AS runs FROM agent_jev_runs GROUP BY mode')).fetchall()
                evaluations = await (await conn.execute('SELECT phase,status,count(*) AS n FROM agent_jev_evaluations GROUP BY phase,status')).fetchall()
            summary = summarize(rows)
            summary['durable_ledger'] = {'runs': ledger, 'evaluations': evaluations}
            summary['case_fingerprint'] = digest(cases)
            summary['configured_models'] = {key: getattr(settings, key) for key in ('DEFAULT_PROVIDER', 'DEFAULT_MODEL', 'JEV_MODEL', 'DECISION_MODEL', 'RESEARCH_MODEL')}
            summary['schedule'] = {'concurrency': args.concurrency, 'pair_pause_seconds': args.pair_pause_seconds,
                                   'row_latency_excludes_pair_pause': True,
                                   'note': 'Pause is an experiment scheduling intervention, not production latency or rate-limit elimination proof'}
            summary['controlled_overrides'] = {key: getattr(settings, key) for key in ('RAG_ENABLED', 'KG_MODE', 'FAST_READ_ENABLED', 'SESSION_MEMORY_MODE', 'RUN_TIMEOUT_SECONDS', 'MAX_GRAPH_STEPS', 'MAX_TOOL_CALLS')}
            output.with_suffix('.summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live', action='store_true')
    parser.add_argument('--database-url', help='Isolated database; prefer JEV_SHADOW_DATABASE_URL to avoid command history')
    parser.add_argument('--out', required=True)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--concurrency', type=int, default=2)
    parser.add_argument('--pair-pause-seconds', type=float, default=0,
                        help='Pause outside timed runs after each off/shadow pair; requires --concurrency 1')
    parser.add_argument('--max-cases', type=int)
    parser.add_argument('--case-id', action='append', help='Repeat to select a pilot subset')
    parser.add_argument('--protocol-research', action='store_true',
                        help='Run only three post-hoc exploratory exercise QA fixtures; main matrix is unchanged')
    args = parser.parse_args()
    if args.max_cases is not None and args.max_cases < 1:
        parser.error('--max-cases must be positive')
    try:
        asyncio.run(run(args))
    except Exception as exc:
        parser.exit(1, 'Shadow experiment failed (' + type(exc).__name__ + '); no raw provider error printed.\n')


if __name__ == '__main__':
    main()
