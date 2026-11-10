"""Benchmark hệ thống multi-agent (GĐ3) với model thật, backend và store tổng hợp trong tiến trình.

    python -m agentic.evaluation.system_benchmark parallel --out eval_results/system   # song song vs tuần tự
    python -m agentic.evaluation.system_benchmark load --levels 1 4 8 16                # nhiều lượt đồng thời
    python -m agentic.evaluation.system_benchmark provider --levels 1 8 16 32           # thông lượng từng model

Mỗi lượt chạy toàn bộ graph (supervisor, agent chuyên trách, cổng xác nhận, synthesizer) như runtime, thẻ xác nhận được
duyệt tự động; thời gian đo là thời gian agent làm việc (không tính lúc chờ người dùng bấm). Backend tổng hợp trả bản
ghi catalog/số đo cố định và nhận mọi bản xem trước, nên chỉ thời gian model và điều phối được đo (backend thật 20–190 ms).
Cấu hình "selected" đọc lựa chọn của ma trận agent × model (agent_model_eval, summary.json).
"""
import argparse
import asyncio
import json
import re
import statistics
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agentic.agents.workflow import build_workflow
from agentic.core.context import RequestContext, request_context
from agentic.core.llm import Models
from agentic.evaluation.agent_model_eval import BASELINE, TZ, eval_settings, norm, percentile
from agentic.observability.telemetry import MeasuredModels
from agentic.services import mode
from agentic.services.memory.store import Store, payload_hash
from agentic.tools.registry import REGISTRY


def uid(n):
    return f'01a15828-0000-7000-8000-{n:012d}'


# Mỗi món tính theo 100 g/100 ml, kèm một khẩu phần hộ gia đình ("1 tô" = 600 G) như catalog thật.
SERVINGS = {'Phở bò': (600, 'G', '1 tô'), 'Bánh mì trứng': (150, 'G', '1 ổ'), 'Cơm tấm sườn': (450, 'G', '1 đĩa'),
            'Bún chả': (500, 'G', '1 suất'), 'Cháo gà': (500, 'G', '1 bát'), 'Sữa đậu nành': (200, 'ML', '1 cốc')}
FOODS = [{'id': uid(i), 'name_vi': vi, 'name_en': en, 'serving_size': '100', 'serving_unit': SERVINGS[vi][1],
          'energy_kcal': f'{float(kcal) * 100 / SERVINGS[vi][0]:g}',
          'portions': [{'label': SERVINGS[vi][2], 'quantity': SERVINGS[vi][0], 'unit': SERVINGS[vi][1]}]}
         for i, (vi, en, kcal) in enumerate([('Phở bò', 'Beef pho', '450'), ('Bánh mì trứng', 'Egg banh mi', '380'),
                                             ('Cơm tấm sườn', 'Broken rice with pork chop', '620'), ('Bún chả', 'Bun cha', '550'),
                                             ('Cháo gà', 'Chicken porridge', '300'), ('Sữa đậu nành', 'Soy milk', '120')], 1)]
EXERCISES = [{'id': uid(20 + i), 'name_vi': vi, 'name_en': en, 'kind': kind}
             for i, (vi, en, kind) in enumerate([('Chạy bộ', 'Running', 'ENDURANCE'), ('Đạp xe', 'Cycling', 'ENDURANCE')])]
READS = {
    'latest_metrics': {'id': 'bm1', 'weight_kg': '70.5', 'body_fat_pct': '18.2', 'recorded_at': '2026-11-06T07:00:00+07:00'},
    'list_metrics': [{'id': 'bm1', 'weight_kg': '70.5', 'recorded_at': '2026-11-06T07:00:00+07:00'}],
    'get_progress': {'days': [{'date': 'today', 'consumed_kcal': 1450, 'target_kcal': 2100, 'protein_g': 85}]},
    'get_nutrition_targets': {'target_kcal': 2100, 'protein_g': 130, 'carbs_g': 250, 'fat_g': 60},
    'list_trainings': [{'id': 't1', 'name': 'Chạy bộ', 'started_at': '2026-11-05T06:00:00+07:00', 'distance_meters': 5000,
                        'duration_seconds': 1800},
                       {'id': 't2', 'name': 'Đạp xe', 'started_at': '2026-11-06T17:00:00+07:00', 'distance_meters': 15000,
                        'duration_seconds': 2700}],
    'list_meals': [], 'current_training_plan': None, 'current_goal': None,
}


class SyntheticBackend:
    """Backend trong tiến trình: catalog và số đo cố định, nhận mọi bản xem trước và lệnh ghi."""
    def __init__(self):
        self.calls = []

    def writes(self):
        return [name for name in self.calls if getattr(REGISTRY.get(name), 'write', False)]

    async def call(self, name, args, token, key=None):
        self.calls.append(name)
        await asyncio.sleep(0.05)  # độ trễ backend điển hình (20–190 ms)
        rows = FOODS if name.endswith('_foods') else EXERCISES if name.endswith('_exercises') else None
        if rows is not None:
            terms = [norm(t) for t in [*(args.get('names') or []), args.get('search'), args.get('query')] if t]
            found = [r for r in rows if not terms or any(t in norm(r['name_vi']) or norm(r['name_vi']) in t
                                                           or t in norm(r['name_en']) for t in terms)]
            if name.startswith('get_'):
                return next((r for r in rows if r['id'] == str(args.get('resource_id'))), None)
            if name.startswith('resolve_'):
                return {'query': terms[0] if terms else '', 'status': 'EXACT' if len(found) == 1 else
                        'POSSIBLE_VARIANT' if found else 'MISSING', 'matches': found}
            return found
        if getattr(REGISTRY.get(name), 'write', False):
            return {'id': str(uuid4()), **{k: v for k, v in args.items() if k != 'resource_id'}}
        return deepcopy(READS.get(name, []))

    async def request(self, method, path, token, *, params=None, body=None, key=None):
        await asyncio.sleep(0.05)
        if path.endswith('preview'):
            return body
        from agentic.tools.integrations.backend_client import BackendError
        raise BackendError(404, 'not available in the benchmark')


class MemoryStore(Store):
    """Hành động chờ xác nhận trong bộ nhớ (cùng kiểm tra băm/phê duyệt của Store)."""
    def __init__(self):
        self.rows = {}

    async def new_action(self, session_id, user_id, tool, payload, preview, expires_at, research_id=None, action_id=None):
        data = dict(action_id=action_id, session_id=session_id, user_id=user_id, tool=tool, payload=deepcopy(payload),
                    preview=preview, expires_at=expires_at.isoformat(), revision=1, payload_hash=payload_hash(tool, payload),
                    research_id=research_id)
        self.rows[action_id] = {'status': 'pending', 'data': data}
        return deepcopy(data)

    async def action(self, action_id):
        return self.rows.get(action_id)

    async def set_action(self, action_id, status, response=None):
        self.rows[action_id]['status'] = status

    async def link_research(self, research_id, resource_id):
        return None


MESSAGES = [
    {'id': 'meal_run_weight', 'text': 'Sáng nay tôi ăn 1 bát phở bò, chạy bộ 5km trong 30 phút, và cho tôi biết cân nặng gần nhất',
     'writes': 2, 'must': r'70[,.]5'},
    {'id': 'lunch_cycle', 'text': 'Ghi giúp bữa trưa 1 đĩa cơm tấm sườn và buổi đạp xe 40 phút được 12km chiều nay', 'writes': 2},
    {'id': 'weight_breakfast', 'text': 'Cân nặng sáng nay của tôi 70 kg, bữa sáng tôi ăn 1 bánh mì trứng', 'writes': 2},
    {'id': 'kcal_sessions', 'text': 'Hôm nay tôi nạp bao nhiêu calo rồi, và tuần này tôi đã có những buổi tập nào?',
     'writes': 0, 'must': r'1[.,]?450'},
    {'id': 'dinner_weight', 'text': 'Tối nay ăn 1 bát bún chả, ghi luôn cân nặng tối nay 69.5kg', 'writes': 2},
    {'id': 'single_meal', 'text': 'Sáng nay tôi ăn 1 bát phở bò', 'writes': 1},
    {'id': 'single_weight', 'text': 'Cân nặng gần nhất của tôi là bao nhiêu?', 'writes': 0, 'must': r'70[,.]5'},
]


def selected_models(path):
    """AGENT_MODELS theo lựa chọn của ma trận; agent giữ baseline thì không cần khai báo."""
    selection = json.loads(Path(path).read_text())['selection']
    return {agent: choice['model'] for agent, choice in selection.items() if choice['model'] != BASELINE}


def config(name, agent_models, parallel):
    return {'name': name, 'parallel': parallel,
            'settings': eval_settings(BASELINE, AGENT_MODELS=agent_models, PARALLEL_AGENTS=parallel)}


async def turn(cfg, message, models=None):
    """Một lượt người dùng tới câu trả lời cuối, thẻ được duyệt tự động. Trả số đo của lượt."""
    settings = cfg['settings']
    backend, store = SyntheticBackend(), MemoryStore()
    graph = build_workflow(models or Models(settings), store, MemorySaver(), None, settings)
    run_id = str(uuid4())
    graph_config = {'configurable': {'thread_id': run_id}, 'recursion_limit': settings.MAX_GRAPH_STEPS}
    marks = (request_context.set(RequestContext('u-bench', 'token', backend)), mode.current.set(mode.NORMAL))
    state = {'messages': [HumanMessage(content=message['text'])], 'user_id': 'u-bench', 'session_id': 's-' + run_id,
             'run_id': run_id, 'tool_outputs': [], 'tool_count': 0, 'status': 'running', 'mode': mode.NORMAL,
             'route_trace': [], 'telemetry': {}, 'execution_records': []}
    working, cards, first, error = 0.0, 0, None, None
    try:
        payload = state
        for _ in range(6):
            started = perf_counter()
            result = await graph.ainvoke(payload, graph_config)
            working += perf_counter() - started
            first = first if first is not None else working
            if result.get('status') != 'pending_confirmation' or not result.get('pending_action'):
                break
            cards += 1
            store.rows[result['pending_action']['action_id']]['status'] = 'approved'
            payload = Command(resume={'decision': 'approve'})
    except Exception as exc:
        result, error = {}, f'{type(exc).__name__}: {str(exc)[:160]}'
    finally:
        request_context.reset(marks[0])
        mode.current.reset(marks[1])
    telemetry = result.get('telemetry') or {}
    reply = result.get('reply') or ''
    ok = (not error and result.get('status') == 'completed' and len(backend.writes()) == message['writes']
          and (not message.get('must') or bool(re.search(message['must'], reply))))
    return {'config': cfg['name'], 'message': message['id'], 'ok': ok, 'error': error, 'status': result.get('status'),
            'seconds': round(working, 3), 'first_card_s': round(first or 0, 3), 'cards': cards, 'writes': len(backend.writes()),
            'fan_out': any(s.get('rule') == 'fan_out' for s in result.get('route_trace') or []),
            'llm_calls': telemetry.get('llm_calls', 0), 'input_tokens': telemetry.get('input_tokens', 0),
            'output_tokens': telemetry.get('output_tokens', 0), 'parallel': telemetry.get('parallel'),
            'agents': {a: v.get('models') for a, v in (telemetry.get('agents') or {}).items()}}


def stats(rows):
    seconds = [r['seconds'] for r in rows if not r['error']]
    return {'turns': len(rows), 'ok_rate': round(sum(r['ok'] for r in rows) / max(1, len(rows)), 3),
            'errors': sum(bool(r['error']) for r in rows), 'p50_s': percentile(seconds, 0.5), 'p95_s': percentile(seconds, 0.95),
            'mean_s': round(statistics.mean(seconds), 3) if seconds else None,
            'llm_calls': round(statistics.mean(r['llm_calls'] for r in rows), 2),
            'input_tokens': round(statistics.mean(r['input_tokens'] for r in rows)),
            'output_tokens': round(statistics.mean(r['output_tokens'] for r in rows))}


async def parallel(args):
    agent_models = selected_models(args.selection)
    configs = [config('baseline-sequential', {}, False), config('baseline-parallel', {}, True),
               config('selected-sequential', agent_models, False), config('selected-parallel', agent_models, True)]
    rows = []
    messages = [m for m in MESSAGES if not args.messages or m['id'] in args.messages]
    configs = [c for c in configs if not args.configs or c['name'] in args.configs]
    for cfg in configs:
        for _ in range(args.repeat):
            for message in messages:
                row = await turn(cfg, message)
                rows.append(row)
                print(json.dumps({k: row[k] for k in ('config', 'message', 'ok', 'seconds', 'fan_out', 'llm_calls', 'error')},
                                 ensure_ascii=False), flush=True)
    summary = {name: stats([r for r in rows if r['config'] == name]) for name in (c['name'] for c in configs)}
    multi = {name: stats([r for r in rows if r['config'] == name and not r['message'].startswith('single')])
             for name in (c['name'] for c in configs)}
    return {'agent_models': agent_models, 'summary': summary, 'multi_intent': multi, 'rows': rows}


async def load(args):
    agent_models = selected_models(args.selection)
    configs = [config('baseline-sequential', {}, False), config('selected-parallel', agent_models, True)]
    results = {}
    for cfg in configs:
        models = Models(cfg['settings'])  # một bộ client cho mọi lượt, như một tiến trình dịch vụ
        for level in args.levels:
            started = perf_counter()
            rows = await asyncio.gather(*(turn(cfg, MESSAGES[i % len(MESSAGES)], models) for i in range(level)))
            wall = perf_counter() - started
            results[f"{cfg['name']}@{level}"] = {**stats(rows), 'concurrency': level, 'wall_s': round(wall, 3),
                                                  'turns_per_min': round(60 * level / wall, 2)}
            print(json.dumps({'config': cfg['name'], 'level': level, **results[f"{cfg['name']}@{level}"]}, ensure_ascii=False), flush=True)
    return {'agent_models': agent_models, 'summary': results}


async def provider(args):
    """Nhiều lời gọi cùng lúc tới một model (một bước của agent nutrition): độ trễ và lỗi theo mức đồng thời."""
    from agentic.core import roster
    tools = [REGISTRY['list_foods'].as_tool(), REGISTRY['create_meals'].as_tool()]
    message = [HumanMessage(content='Sáng nay tôi ăn 1 bát phở bò, ghi lại giúp tôi.')]
    results = {}
    for model in args.models:
        bound = MeasuredModels(Models(eval_settings(model))).get('tool').bind_tools(tools, parallel_tool_calls=False)
        for level in args.levels:
            async def one():
                started = perf_counter()
                try:
                    with roster.acting(roster.NUTRITION):
                        reply = await bound.ainvoke(message)
                    return perf_counter() - started, bool(reply.tool_calls), None
                except Exception as exc:
                    return perf_counter() - started, False, type(exc).__name__
            started = perf_counter()
            rows = await asyncio.gather(*(one() for _ in range(level)))
            wall = perf_counter() - started
            seconds = [s for s, _, e in rows if not e]
            results[f'{model}@{level}'] = {'model': model, 'concurrency': level, 'p50_s': percentile(seconds, 0.5),
                                           'p95_s': percentile(seconds, 0.95), 'errors': sum(bool(e) for _, _, e in rows),
                                           'tool_call_rate': round(sum(ok for _, ok, _ in rows) / level, 3),
                                           'calls_per_s': round(level / wall, 2)}
            print(json.dumps(results[f'{model}@{level}'], ensure_ascii=False), flush=True)
    return {'summary': results}


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('command', choices=['parallel', 'load', 'provider'])
    parser.add_argument('--selection', default='eval_results/agent_models/summary.json')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--levels', type=int, nargs='+', default=[1, 4, 8, 16])
    parser.add_argument('--models', nargs='+', default=[BASELINE, 'gemma-4-26B-A4B-it'])
    parser.add_argument('--messages', nargs='+', help='chỉ chạy các tin nhắn này (id)')
    parser.add_argument('--configs', nargs='+', help='chỉ chạy các cấu hình này (parallel)')
    parser.add_argument('--out', default='eval_results/system')
    args = parser.parse_args(argv)
    result = await {'parallel': parallel, 'load': load, 'provider': provider}[args.command](args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f'{args.command}.json').write_text(json.dumps({'generated_at': datetime.now(TZ).isoformat(), **result},
                                                         ensure_ascii=False, indent=2, default=str))
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
