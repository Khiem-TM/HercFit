"""Session memory evaluation with the real models, backend and Redis.

Each case states facts early in a fresh session, pushes them out of the verbatim
window with filler turns, then asks for them back. Seed the evaluation user first:
    python -m agentic.evaluation.kg_eval seed
    python -m agentic.evaluation.memory_eval run --modes off,on --out /tmp/memory_eval

Scoring is rule-based: every keyword group must appear in the probe reply.
'outside' cases measure recall beyond the window; 'inside' cases guard against
regressions within it. Filler turns are short acknowledgements to keep model cost low.
"""
import argparse
import asyncio
import csv
import json
import statistics
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from agentic.core.app.config import agent_settings
from agentic.evaluation.kg_eval import EVAL_USER, normalize, token

CASES = Path(__file__).parent / 'datasets' / 'memory_cases.jsonl'
FILLER = ['Cảm ơn bạn nhé.', 'Ok, mình hiểu rồi.', 'Nghe hợp lý đấy.', 'Tiếp tục nhé.', 'Được, cảm ơn.']


def load_cases(only=()):
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    return [c for c in cases if not only or c['id'] in only or c['scope'] in only]


async def run_case(runtime, backend, case, filler, mode):
    from agentic.core.context import RequestContext, request_context
    from agentic.core.app.schemas.request import ChatRequest
    session_id, jwt = 'memeval-' + uuid4().hex, token()

    async def say(message):
        mark = request_context.set(RequestContext(str(EVAL_USER), jwt, backend))
        try:
            return await runtime.chat(ChatRequest(message=message, session_id=session_id), str(EVAL_USER))
        finally:
            request_context.reset(mark)
    for message in case['facts']:
        await say(message)
    for i in range(filler if case['scope'] == 'outside' else 0):
        await say(FILLER[i % len(FILLER)])
    if runtime.memory is not None:
        # Score the settled summary, not a race with its background job.
        await asyncio.gather(*list(runtime.memory._tasks.values()), return_exceptions=True)
    started = perf_counter()
    response = await say(case['probe'])
    elapsed = (perf_counter() - started) * 1000
    values = (await runtime.state(response.run_id)).values
    telemetry = values.get('telemetry') or {}
    memory = values.get('session_memory') or {}
    reply = normalize(response.reply)
    await runtime.clear(session_id, str(EVAL_USER))
    return {'mode': mode, 'id': case['id'], 'scope': case['scope'], 'status': response.status,
            'recall_ok': all(any(normalize(k) in reply for k in group) for group in case['keywords']),
            'input_tokens': telemetry.get('input_tokens', 0), 'llm_calls': telemetry.get('llm_calls', 0),
            'latency_ms': round(elapsed), 'summary_chars': len(memory.get('summary') or ''),
            'reply': response.reply[:300].replace('\n', ' ')}


async def run_mode(mode, cases, filler, repeat):
    from agentic.core.app.main import create_agentic_app
    app = create_agentic_app(agent_settings.model_copy(update={'SESSION_MEMORY_MODE': mode}))
    rows = []
    async with app.router.lifespan_context(app):
        for attempt in range(repeat):
            for case in cases:
                try:
                    row = await run_case(app.state.runtime, app.state.backend, case, filler, mode)
                except Exception as exc:
                    row = {'mode': mode, 'id': case['id'], 'scope': case['scope'], 'status': 'error', 'recall_ok': False,
                           'input_tokens': 0, 'llm_calls': 0, 'latency_ms': None, 'summary_chars': 0,
                           'reply': 'ERROR ' + type(exc).__name__}
                rows.append({**row, 'attempt': attempt})
                print(f"[{mode}#{attempt}] {case['id']:<10} recall={row['recall_ok']!s:<5} tok={row['input_tokens']} "
                      f"{row['latency_ms']}ms summary={row['summary_chars']}", flush=True)
    return rows


def summarize(rows):
    def pct(values):
        return f'{100 * sum(values) / len(values):.0f}%' if values else '-'
    lines = ['| mode | scope | n | nhớ đúng | input tokens (probe) | latency p50 (probe) | có tóm tắt |', '|---|---|---|---|---|---|---|']
    for mode in dict.fromkeys(r['mode'] for r in rows):
        for scope in ('outside', 'inside'):
            sel = [r for r in rows if r['mode'] == mode and r['scope'] == scope]
            if sel:
                latency = sorted(r['latency_ms'] for r in sel if r['latency_ms'] is not None)
                lines.append(f"| {mode} | {scope} | {len(sel)} | {pct([r['recall_ok'] for r in sel])} | "
                             f"{statistics.mean(r['input_tokens'] for r in sel):.0f} | "
                             f"{latency[len(latency) // 2] if latency else '-'} | {pct([r['summary_chars'] > 0 for r in sel])} |")
    return '\n'.join(lines)


async def run(modes, filler, repeat, out, only):
    cases, rows = load_cases(only), []
    for mode in modes:
        rows += await run_mode(mode, cases, filler, repeat)
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
    parser.add_argument('command', choices=['run'])
    parser.add_argument('--modes', default='off,on')
    # 22 two-message turns move a first-turn fact past the default 40-message window.
    parser.add_argument('--filler', type=int, default=22)
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--cases', default='', help='comma-separated case ids or scopes')
    parser.add_argument('--out', default='/tmp/memory_eval')
    args = parser.parse_args()
    asyncio.run(run(args.modes.split(','), args.filler, args.repeat, Path(args.out), set(filter(None, args.cases.split(',')))))


if __name__ == '__main__':
    main()
