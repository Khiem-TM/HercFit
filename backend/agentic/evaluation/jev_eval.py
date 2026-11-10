"""Opt-in paired Jev evaluation on an isolated fixture; never approves a write.

Cases are synthetic review prompts, not a validated accuracy dataset. A passing
report requires complete human reviews, known usage/prices and matched inputs.
Run/report help: python -m agentic.evaluation.jev_eval --help
"""
import argparse
import asyncio
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import uuid4

CASES = Path(__file__).parent / 'datasets' / 'jev_cases.jsonl'
REVIEW_FIELDS = ('correctness', 'citation', 'completeness', 'valid_completion')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def read_jsonl(path):
    with Path(path).open() as file:
        return [json.loads(line) for line in file if line.strip()]


def load_cases(split='holdout', path=CASES):
    rows = read_jsonl(path)
    ids = [row['case_id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate case IDs')
    splits = defaultdict(set)
    for row in rows:
        splits[row['scenario_id']].add(row['split'])
    if any(len(values) != 1 for values in splits.values()):
        raise ValueError('Scenario split leakage')
    return [row for row in rows if split == 'all' or row['split'] == split]


def measured_usage(telemetry):
    """Never reinterpret missing usage or missing configured prices as zero."""
    result = {}
    for name, prefix in (('llm', ''), ('jev', 'jev_'), ('shadow', 'jev_shadow_')):
        calls = telemetry.get('llm_calls' if name == 'llm' else prefix + 'calls', 0)
        usage_unknown = telemetry.get(('llm_' if name == 'llm' else prefix) + 'usage_unknown_calls', 0)
        cost_unknown = telemetry.get(('llm_' if name == 'llm' else prefix) + 'cost_unknown_calls', 0)
        values = (telemetry.get(prefix + 'input_tokens'), telemetry.get(prefix + 'output_tokens'))
        tokens = None if usage_unknown or calls and any(value is None for value in values) else sum(value or 0 for value in values)
        price = telemetry.get('llm_cost' if name == 'llm' else prefix + 'cost')
        cost = None if cost_unknown or calls and price is None else (price or 0)
        result[name] = {'calls': calls, 'tokens': tokens, 'cost': cost}
    for field in ('tokens', 'cost'):
        values = [result[name][field] for name in ('llm', 'jev', 'shadow')]
        result[field] = None if any(value is None for value in values) else sum(values)
    # Missing telemetry altogether means instrumentation was not observed.
    if not telemetry:
        result['tokens'] = result['cost'] = None
    return result


def percentile(values, p):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * p
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def pair_key(row):
    return tuple(row.get(key) for key in ('case_id', 'repeat', 'fixture_id', 'corpus_revision',
                                        'cache_condition', 'model_fingerprint', 'cases_fingerprint', 'case_fingerprint'))


def review_key(row):
    return (*pair_key(row), row.get('mode'))


def report_rows(rows, reviews=(), *, cases=None, repeat=3):
    cases = cases if cases is not None else load_cases()
    expected_ids = {case['case_id'] for case in cases}
    pairs, review_map = defaultdict(dict), {}
    blockers = []
    for review in reviews:
        key = review_key(review)
        if key in review_map:
            blockers.append('duplicate_review')
        review_map[key] = review
    for row in rows:
        if row.get('case_id') not in expected_ids:
            blockers.append('unexpected_case_or_split')
            continue
        key, mode = pair_key(row), row.get('mode')
        if mode not in {'off', 'enforce'} or mode in pairs[key]:
            blockers.append('duplicate_or_invalid_mode')
        pairs[key][mode] = row
    expected_slots = {(case_id, repetition) for case_id in expected_ids for repetition in range(1, repeat + 1)}
    actual_slots = {(key[0], key[1]) for key in pairs}
    if actual_slots != expected_slots or len(pairs) != len(expected_slots):
        blockers.append('incomplete_case_repeat_coverage')
    if any(set(pair) != {'off', 'enforce'} for pair in pairs.values()):
        blockers.append('unpaired_or_mismatched_fingerprints')
    fingerprints = {key[2:7] for key in pairs}
    if len(fingerprints) != 1 or any(any(value is None or value == '' for value in key[2:]) for key in pairs):
        blockers.append('inconsistent_or_missing_fixture_model_fingerprint')
    expected_by_id = {case['case_id']: digest(case) for case in cases}
    if any(row.get('cases_fingerprint') != digest(cases) for row in rows):
        blockers.append('case_set_changed')
    if any(row.get('case_fingerprint') != expected_by_id.get(row.get('case_id')) for row in rows):
        blockers.append('case_content_changed')
    if not expected_ids:
        blockers.append('empty_case_set')
    metrics = {}
    for mode in ('off', 'enforce'):
        mode_rows = [pair[mode] for pair in pairs.values() if mode in pair]
        judged = [review_map.get(review_key(row), {}) for row in mode_rows]
        if not mode_rows or any(any(type(review.get(field)) is not bool for field in REVIEW_FIELDS) for review in judged):
            blockers.append('incomplete_human_reviews')
        if any(row.get('error') for row in mode_rows):
            blockers.append('execution_errors')
        tokens = [row.get('usage', {}).get('tokens') for row in mode_rows]
        costs = [row.get('usage', {}).get('cost') for row in mode_rows]
        if any(value is None for value in tokens + costs):
            blockers.append('unknown_usage_or_cost')
        eligible = [row for row in mode_rows if row.get('routing_eligible')]
        metrics[mode] = {
            'count': len(mode_rows),
            'tokens': None if not tokens or any(value is None for value in tokens) else sum(tokens),
            'cost': None if not costs or any(value is None for value in costs) else sum(costs),
            'latency_p50_ms': percentile([row['latency_ms'] for row in mode_rows], .50),
            'latency_p95_ms': percentile([row['latency_ms'] for row in mode_rows], .95),
            'routing_accuracy': mean(row.get('actual_domain') == row.get('expected_domain') for row in eligible) if eligible else None,
            'quality': {field: mean(review[field] for review in judged) if judged and all(type(review.get(field)) is bool for review in judged) else None for field in REVIEW_FIELDS},
            'web_calls': sum(row.get('web_usage', {}).get('web', 0) for row in mode_rows),
            'web_cost': None,  # Tavily prices are not inferred from request counts.
        }
    savings = {}
    for field in ('tokens', 'cost', 'latency_p95_ms'):
        before, after = metrics['off'][field], metrics['enforce'][field]
        savings[field] = None if before is None or after is None or before <= 0 else 1 - after / before
    goals = {'tokens': savings['tokens'] is not None and savings['tokens'] >= .20,
             'cost': savings['cost'] is not None and savings['cost'] >= .15,
             'latency_p95': savings['latency_p95_ms'] is not None and savings['latency_p95_ms'] >= .15,
             'routing': metrics['enforce']['routing_accuracy'] is not None and metrics['enforce']['routing_accuracy'] >= .95,
             'quality': all(metrics['off']['quality'][field] is not None and metrics['enforce']['quality'][field] is not None
                            and metrics['enforce']['quality'][field] >= metrics['off']['quality'][field] for field in REVIEW_FIELDS)}
    return {'accepted': not blockers and all(goals.values()), 'blockers': sorted(set(blockers)),
            'goals': goals, 'savings': savings, 'metrics': metrics,
            'note': 'Synthetic prompts require human-reviewed fixture/corpus answers; this report alone does not authorize canary promotion.'}


async def run(args):
    if not args.allow_live or not args.fixture_id or not args.corpus_revision:
        raise ValueError('Live evaluation requires --allow-live, --fixture-id and --corpus-revision for an isolated backend')
    token = os.environ.get('JEV_EVAL_TOKEN')
    if not token:
        raise ValueError('Set JEV_EVAL_TOKEN to the isolated fixture account token')
    from agentic.core.app.config import agent_settings
    from agentic.core.context import RequestContext, request_context
    from agentic.core.app.main import create_agentic_app
    from agentic.core.app.schemas.request import ChatRequest
    from agentic.observability.settings import ObservabilitySettings

    cases = load_cases(args.split, args.cases)
    if not cases:
        raise ValueError('No selected cases')
    settings = agent_settings.model_copy(update={'JEV_ENFORCE_PERCENT': 100})
    settings.check_jev()
    model_spec = {key: getattr(settings, key) for key in ('DEFAULT_PROVIDER', 'DEFAULT_MODEL', 'DECISION_MODEL', 'RESPONSE_MODEL',
                  'TOOL_MODEL', 'RESEARCH_MODEL', 'MODEL_BASE_URL', 'FPT_BASE_URL', 'JEV_MODEL', 'JEV_BASE_URL',
                  'JEV_POLICY_VERSION', 'RAG_ENABLED', 'KG_MODE', 'FAST_READ_ENABLED', 'RESEARCH_SOURCE_DOMAINS')}
    model_spec['llm_prices'] = ObservabilitySettings().MODEL_PRICES
    model_spec['jev_prices'] = {key: getattr(settings, key) for key in ('JEV_INPUT_PRICE_PER_MILLION', 'JEV_OUTPUT_PRICE_PER_MILLION')}
    manifest = {'fixture_id': args.fixture_id, 'corpus_revision': args.corpus_revision,
                'cache_condition': args.cache_condition, 'model_fingerprint': digest(model_spec),
                'cases_fingerprint': digest(cases), 'split': args.split}
    output = Path(args.out)
    # Exclusive creation avoids mixing incomplete or stale benchmark runs.
    with output.with_suffix('.runs.jsonl').open('x') as runs, output.with_suffix('.reviews.jsonl').open('x') as reviews:
        # Alternate mode order by repetition to reduce systematic time/order bias.
        for repetition in range(1, args.repeat + 1):
            for mode in (('off', 'enforce') if repetition % 2 else ('enforce', 'off')):
                app = create_agentic_app(settings.model_copy(update={'JEV_MODE': mode}))
                async with app.router.lifespan_context(app):
                    user = await app.state.backend.identity(token)
                    context = RequestContext(str(user.id), token, app.state.backend, (user.fullname, str(user.email)))
                    marker = request_context.set(context)
                    try:
                        for case in cases:
                            session = 'jeveval-' + uuid4().hex
                            # History is replayed as user messages; no confirmation endpoint is called.
                            for message in case.get('history', []):
                                await app.state.runtime.chat(ChatRequest(message=message, session_id=session), str(user.id))
                            started = perf_counter()
                            row = {**manifest, 'case_id': case['case_id'], 'scenario_id': case['scenario_id'],
                                   'case_fingerprint': digest(case), 'repeat': repetition, 'mode': mode,
                                   'routing_eligible': case['routing_eligible'], 'expected_domain': case['expected_domain']}
                            try:
                                response = await app.state.runtime.chat(ChatRequest(message=case['message'], session_id=session), str(user.id))
                                snapshot = await app.state.runtime.state(response.run_id)
                                values = snapshot.values if snapshot else {}
                                telemetry = values.get('telemetry', {})
                                row.update(latency_ms=round((perf_counter() - started) * 1000, 3),
                                           actual_domain=(values.get('turn') or {}).get('domain'), status=response.status,
                                           usage=measured_usage(telemetry), telemetry=telemetry,
                                           web_usage=values.get('research_usage', {}),
                                           research_result=values.get('research_result'),
                                           reported_jev_models=sorted({event['model'] for event in values.get('jev_events', []) if event.get('model')}),
                                           error='run_failed' if response.status == 'failed' else None)
                                review = {**row, 'message': case['message'], 'reply': response.reply, 'sources': response.sources,
                                          'evidence_rubric': case['evidence_rubric'], 'expected_statuses': case['expected_statuses'],
                                          'human_review_required': True, **dict.fromkeys(REVIEW_FIELDS)}
                            except Exception as exc:
                                row.update(latency_ms=round((perf_counter() - started) * 1000, 3), usage={'tokens': None, 'cost': None},
                                           error=type(exc).__name__)
                                review = {**row, 'evidence_rubric': case['evidence_rubric'], **dict.fromkeys(REVIEW_FIELDS)}
                            runs.write(json.dumps(row, ensure_ascii=False) + '\n'); runs.flush()
                            reviews.write(json.dumps(review, ensure_ascii=False) + '\n'); reviews.flush()
                    finally:
                        request_context.reset(marker)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    execute = sub.add_parser('run', help='Opt-in real graph evaluation; consumes model/search credits and stores isolated previews')
    execute.add_argument('--allow-live', action='store_true')
    execute.add_argument('--fixture-id', required=True)
    execute.add_argument('--corpus-revision', required=True)
    execute.add_argument('--cache-condition', required=True, help='Declared identical cache policy; runner does not flush remote/provider caches')
    execute.add_argument('--split', choices=('calibration', 'holdout'), default='holdout')
    execute.add_argument('--repeat', type=int, default=3)
    execute.add_argument('--cases', type=Path, default=CASES)
    execute.add_argument('--out', required=True, help='New local output prefix; creates .runs.jsonl and .reviews.jsonl')
    report = sub.add_parser('report', help='Offline report; incomplete/unknown results never pass')
    report.add_argument('--results', required=True, type=Path)
    report.add_argument('--reviews', type=Path)
    report.add_argument('--split', choices=('calibration', 'holdout'), default='holdout')
    report.add_argument('--repeat', type=int, default=3)
    report.add_argument('--cases', type=Path, default=CASES)
    args = parser.parse_args()
    if args.repeat < 3:
        parser.error('--repeat must be at least 3')
    if args.command == 'report':
        print(json.dumps(report_rows(read_jsonl(args.results), read_jsonl(args.reviews) if args.reviews else (),
                                     cases=load_cases(args.split, args.cases), repeat=args.repeat), ensure_ascii=False, indent=2))
    else:
        try:
            asyncio.run(run(args))
        except ValueError as exc:
            parser.error(str(exc))


if __name__ == '__main__':
    main()
