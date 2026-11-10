"""Bounded live shadow diagnostics on frozen synthetic gates, not a production benchmark.

The real JevService/client run in shadow mode. The explicitly in-memory ledger
does not establish PostgreSQL durability, worker isolation or workflow savings.
No backend authentication, user records, writes, web search or LLM answers run.
"""
from agentic.prompts.registry import get_questions
import argparse
import asyncio
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import HumanMessage

from agentic.agents.orchestration_agent import JEV_ROUTING_QUESTIONS, jev_read_domain, jev_routing_projection
from agentic.services.jev import JevService
from agentic.evaluation.jev_eval import digest, load_cases, percentile
from agentic.research.contracts import ResearchDraft


MAX_ROUTING_CASES = 80
MAX_REPEAT = 3
MAX_CONCURRENCY = 3
MAX_CALLS = 300


class SyntheticMemoryLedger:
    """Atomic fixture-only ledger; intentionally not a PostgreSQL substitute."""
    def __init__(self):
        self.lock = asyncio.Lock()
        self.runs, self.rows = {}, {}

    async def reserve(self, state, phase, fingerprint, mode):
        async with self.lock:
            run = self.runs.setdefault(state['run_id'], {'mode': mode, 'routing': 0, 'research': 0})
            key = (state['run_id'], phase, fingerprint)
            if key in self.rows:
                row = self.rows[key]
                return {'status': 'cached' if 'result' in row else 'pending', 'mode': run['mode'], **deepcopy(row)}
            kind, limit = ('routing', 1) if phase == 'routing' else ('research', 2)
            if run[kind] >= limit:
                return {'status': 'budget_exhausted', 'mode': run['mode']}
            run[kind] += 1
            row = {'evaluation_id': str(uuid4())}
            self.rows[key] = row
            return {'status': 'reserved', 'mode': run['mode'], **row}

    async def complete(self, evaluation_id, result):
        async with self.lock:
            row = next(row for row in self.rows.values() if row['evaluation_id'] == evaluation_id)
            row['result'] = deepcopy(result)


def exact_research_questions():
    """Read the same versioned questions the application uses."""
    return {phase: get_questions('research.' + phase) for phase in ('local', 'final')}


def routing_cases(max_cases=MAX_ROUTING_CASES):
    if not 1 <= max_cases <= MAX_ROUTING_CASES:
        raise ValueError('max routing cases must be between 1 and 80')
    grouped = defaultdict(list)
    for row in load_cases('holdout'):
        grouped[row['scenario_id']].append(row)
    selected = [row for group in grouped.values() for row in group[:2]][:max_cases]
    return [{'case_id': row['case_id'], 'scenario_id': row['scenario_id'], 'phase': 'routing',
             'language': row['language'], 'category': row['category'], 'message': row['message'],
             'expected_domain': row['expected_domain'], 'routing_eligible': row['routing_eligible']}
            for row in selected]


def research_cases():
    """Paired semantic faults/controls pass the current deterministic claim checks."""
    texts = {
        'en': (
            'Which group may use EvalMove Alpha, and which equipment does it require?',
            'EvalMove Alpha applies only to trained adult sprinters.',
            'EvalMove Alpha requires a stable bench.',
            'EvalMove Alpha applies to all untrained beginners.',
            'EvalMove Alpha requires a suspended strap and forbids using a bench.',
            'The target group and required equipment are not documented.'),
        'vi': (
            'Nhóm nào được áp dụng EvalMove Alpha và cần thiết bị nào?',
            'EvalMove Alpha chỉ áp dụng cho người chạy nước rút trưởng thành đã qua đào tạo.',
            'EvalMove Alpha yêu cầu một ghế tập vững chắc.',
            'EvalMove Alpha áp dụng cho mọi người mới chưa qua đào tạo.',
            'EvalMove Alpha yêu cầu dây treo và cấm sử dụng ghế tập.',
            'Chưa có tài liệu về nhóm áp dụng hoặc thiết bị cần thiết.'),
    }
    cases = []
    for language, (request, group, equipment, unsupported, contradiction, empty) in texts.items():
        source_id = 'synthetic:' + language
        sources = [{'source_id': source_id, 'title': 'Synthetic evaluation fixture',
                    'content': group + ' ' + equipment}]
        claims = [{'claim': quote, 'field': 'answer', 'source_id': source_id, 'quote': quote,
                   'applicable': True, 'authority': 'primary'} for quote in (group, equipment)]
        draft = ResearchDraft(claims=claims, sufficient=True).model_dump(mode='json')
        base = {'request': request, 'sources': sources, 'draft': draft}
        for kind in ('good', 'unsupported_applicability', 'omitted_objective', 'unreported_conflict'):
            projection = deepcopy(base)
            if kind == 'unsupported_applicability':
                projection['draft']['claims'][0]['claim'] = unsupported
            elif kind == 'omitted_objective':
                projection['draft']['claims'] = projection['draft']['claims'][:1]
            elif kind == 'unreported_conflict':
                projection['sources'].append({'source_id': source_id + ':conflict',
                    'title': 'Conflicting synthetic protocol', 'content': contradiction})
            cases.append({'case_id': 'final_' + kind + '_' + language, 'phase': 'final',
                          'language': language, 'kind': kind, 'expected_reject': kind != 'good',
                          'projection': projection})
        for insufficient in (False, True):
            cases.append({'case_id': 'local_' + ('insufficient_' if insufficient else 'sufficient_') + language,
                          'phase': 'local', 'language': language, 'expected_web_fallback': insufficient,
                          'projection': {'request': request, 'sources': [{**sources[0],
                              'content': empty if insufficient else sources[0]['content']}]}})
    return cases


def state_for(case):
    return {'run_id': str(uuid4()), 'session_id': 'synthetic-session-' + uuid4().hex,
            'user_id': 'synthetic-gate-owner',
            'messages': [HumanMessage(content=case.get('message', 'Synthetic research fixture'))]}


def counterfactual(phase, result):
    if result.get('status') != 'ok':
        return {'decision': None, 'uncertain': True}
    if phase == 'routing':
        domain = jev_read_domain(result)
        return {'decision': domain, 'uncertain': domain is None,
                'top_choice': result.get('answers', {}).get('route', {}).get('choice')}
    answers = result.get('answers', {})
    values = {key: value.get('noul') for key, value in answers.items()}
    if phase == 'local':
        p = values.get('local_insufficient')
        return {'decision': p >= .90 if p is not None else None,
                'uncertain': p is None or .10 < p < .90}
    supported, conflict, sufficient = (values.get(key) for key in ('supported', 'conflict', 'sufficient'))
    reject = (supported is not None and supported <= .10
              or conflict is not None and conflict >= .90
              or sufficient is not None and sufficient <= .10)
    confident_accept = supported is not None and supported >= .90 and conflict is not None and conflict <= .10 and sufficient is not None and sufficient >= .90
    return {'decision': bool(reject), 'uncertain': not reject and not confident_accept}


async def evaluate_cases(service, cases, *, repeat=3, concurrency=3, max_calls=MAX_CALLS, on_row=None):
    if service.settings.JEV_MODE != 'shadow':
        raise ValueError('Diagnostic evaluation requires JEV_MODE=shadow')
    if not 1 <= repeat <= MAX_REPEAT or not 1 <= concurrency <= MAX_CONCURRENCY:
        raise ValueError('repeat and concurrency must each be between 1 and 3')
    if not 1 <= max_calls <= MAX_CALLS:
        raise ValueError('max calls must be between 1 and 300')
    questions = exact_research_questions()
    prepared = []
    for repetition in range(1, repeat + 1):
        for case in cases:
            state = state_for(case)
            projection = jev_routing_projection(state) if case['phase'] == 'routing' else case['projection']
            prepared.append((case, repetition, state, projection))
    if sum(projection is not None for _, _, _, projection in prepared) > max_calls:
        raise ValueError('Requested evaluation exceeds max-calls; no provider calls made')
    semaphore = asyncio.Semaphore(concurrency)
    async def one(case, repetition, state, projection):
        row = {key: value for key, value in case.items() if key != 'projection'}
        row.update(repeat=repetition, fixture_fingerprint=digest(case), mode='shadow', ledger='synthetic_in_memory')
        if projection is None:
            result = {'status': 'skipped', 'reason': 'application_projection_excluded', 'attempted': False}
        else:
            phase_questions = JEV_ROUTING_QUESTIONS if case['phase'] == 'routing' else questions[case['phase']]
            row['projection_fingerprint'] = digest(projection)
            row['questions_fingerprint'] = digest(phase_questions)
            async with semaphore:
                result = await service.evaluate(state, case['phase'], projection, phase_questions)
        row['result'] = result
        row['counterfactual'] = counterfactual(case['phase'], result)
        if on_row:
            on_row(row)
        return row
    return await asyncio.gather(*(one(*item) for item in prepared))


def summary(rows):
    routing = [row for row in rows if row['phase'] == 'routing']
    eligible = [row for row in routing if row['routing_eligible']]
    accepted = [row for row in routing if row['counterfactual']['decision'] is not None]
    accepted_eligible = [row for row in accepted if row['routing_eligible']]
    correct = [row for row in accepted if row['routing_eligible'] and row['counterfactual']['decision'] == row['expected_domain']]
    ok_eligible = [row for row in eligible if row['result']['status'] == 'ok']
    research = {}
    for phase, label in (('local', 'expected_web_fallback'), ('final', 'expected_reject')):
        group = [row for row in rows if row['phase'] == phase]
        valid = [row for row in group if row['result']['status'] == 'ok']
        positive = [row for row in valid if row[label]]
        negative = [row for row in valid if not row[label]]
        research[phase] = {'count': len(group), 'valid': len(valid),
            'uncertain': sum(row['counterfactual']['uncertain'] for row in group),
            'true_positives': sum(row['counterfactual']['decision'] is True for row in positive),
            'false_negatives': sum(row['counterfactual']['decision'] is not True for row in positive),
            'false_positives': sum(row['counterfactual']['decision'] is True for row in negative),
            'true_negatives': sum(row['counterfactual']['decision'] is False for row in negative),
            'positive_references': len(positive), 'negative_references': len(negative)}
    attempted = [row['result'] for row in rows if row['result'].get('attempted')]
    unknown_usage = sum(result.get('usage') is None for result in attempted)
    unknown_cost = sum(result.get('cost') is None for result in attempted)
    def latency(phase):
        times = [row['result']['duration_ms'] for row in rows if row['phase'] == phase and row['result'].get('attempted')]
        return {'p50_ms': percentile(times, .50), 'p95_ms': percentile(times, .95)}
    return {'scope': 'Synthetic live gate-only shadow diagnostics; in-memory ledger; no baseline LLM or production quality claims',
        'production_promotion_accepted': False,
        'routing': {'cases': len(routing), 'reference_eligible': len(eligible),
            'application_projection_excluded': sum(row['result']['status'] == 'skipped' for row in routing),
            'top_choice_accuracy_on_valid_eligible': (
                sum(row['counterfactual'].get('top_choice') == row['expected_domain'] for row in ok_eligible)
                / len(ok_eligible) if ok_eligible else None),
            'accepted_shortcuts': len(accepted),
            'accepted_eligible_shortcuts': len(accepted_eligible),
            'coverage': len(accepted_eligible) / len(eligible) if eligible else None,
            'correct_shortcut_coverage': len(correct) / len(eligible) if eligible else None,
            'selective_accuracy': len(correct) / len(accepted) if accepted else None,
            'false_shortcuts': len(accepted) - len(correct),
            'exclusion_probability_failures': {
                name: sum((row['result'].get('answers', {}).get(name, {}).get('noul') or 0) > .10
                          for row in routing if row['result']['status'] == 'ok')
                for name in ('mutation', 'multiple', 'dependency', 'web')},
            'uncertain_or_excluded': sum(row['counterfactual']['uncertain'] for row in routing)},
        'research': research,
        'measurement': {'rows': len(rows), 'attempts': len(attempted),
            'valid_responses': sum(result['status'] == 'ok' for result in attempted),
            'status_counts': dict(Counter(row['result']['status'] for row in rows)),
            'failure_reasons': dict(Counter(row['result'].get('reason', 'unknown') for row in rows
                                           if row['result']['status'] not in {'ok', 'skipped'})),
            'unknown_usage_calls': unknown_usage, 'unknown_cost_calls': unknown_cost,
            'tokens': None if unknown_usage else sum(result['usage']['total_tokens'] for result in attempted),
            'cost': None if unknown_cost else sum(result['cost'] for result in attempted),
            'known_cost_subtotal': sum(result.get('cost') or 0 for result in attempted),
            'latency_by_phase': {phase: latency(phase) for phase in ('routing', 'local', 'final')},
            'resolved_models': sorted({result['model'] for result in attempted if result.get('model')}),
            'unexpected_enforced_results': sum(bool(result.get('enforced')) for result in attempted)},
        'limitations': ['Ground truth is synthetic and not a human-reviewed scientific benchmark.',
            'No real workflow/LLM/backend/web answers or PostgreSQL durability measured.',
            'Counterfactual decisions do not demonstrate enforce-mode savings or quality.',
            'Shadow preserves baseline decisions and adds model spend/latency.']}


async def run(args):
    if not args.allow_live:
        raise ValueError('Pass --allow-live to consume gateway credits on synthetic fixtures')
    # Import only at the explicit live entrypoint; pure tests need no .env/key.
    from agentic.tools.integrations.jev import JevClient
    from agentic.core.app.config import agent_settings
    settings = agent_settings.model_copy(update={'JEV_MODE': 'shadow'})
    settings.check_jev()
    cases = routing_cases(args.max_routing_cases) + research_cases()
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    if any(output.with_suffix(suffix).exists() for suffix in ('.runs.jsonl', '.summary.json', '.fixtures.json')):
        raise ValueError('Output prefix already exists; choose a fresh prefix')
    client = JevClient(settings)
    service = JevService(client, None, settings, ledger=SyntheticMemoryLedger())
    try:
        with output.with_suffix('.runs.jsonl').open('x') as file:
            count = 0
            def write(row):
                nonlocal count
                count += 1
                file.write(json.dumps(row, ensure_ascii=False) + '\n'); file.flush()
                if count % 20 == 0:
                    print(json.dumps({'completed': count}), flush=True)
            rows = await evaluate_cases(service, cases, repeat=args.repeat, concurrency=args.concurrency,
                                        max_calls=args.max_calls, on_row=write)
        report = summary(rows)
        report['manifest'] = {'fixture_fingerprint': digest(cases), 'case_count': len(cases),
            'repeat': args.repeat, 'concurrency': args.concurrency, 'max_calls': args.max_calls,
            'configured_model': settings.JEV_MODEL, 'policy_version': settings.JEV_POLICY_VERSION,
            'cache_policy': 'Fresh synthetic run IDs; no ledger cache reuse; provider cache not controlled'}
        output.with_suffix('.summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        output.with_suffix('.fixtures.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live', action='store_true')
    parser.add_argument('--max-routing-cases', type=int, default=MAX_ROUTING_CASES)
    parser.add_argument('--repeat', type=int, default=MAX_REPEAT)
    parser.add_argument('--concurrency', type=int, default=MAX_CONCURRENCY)
    parser.add_argument('--max-calls', type=int, default=MAX_CALLS)
    parser.add_argument('--out', required=True, help='New output prefix for .runs.jsonl/.summary.json/.fixtures.json')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
