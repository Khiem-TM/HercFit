"""Routing of personal advice vs. general knowledge, with the real router model and a synthetic user.

    python -m evaluation.personalization_eval --repeat 2 --out eval_results/personalization

Each case sends one message through OrchestrationAgent.decide (router model + code rules) with a
fictional athlete's context card; no real account, token or backend is used. Scored per case:
personalize flag, topic, final action, whether the route asks for facts the card already holds,
and which reads would run (code-owned deep reads for the topic).
"""
import argparse
import asyncio
import json
import statistics
from datetime import datetime
from pathlib import Path
from time import perf_counter

from langchain_core.messages import HumanMessage

from agentic.agents.orchestration_agent import OrchestrationAgent
from agentic.core.app.config import agent_settings
from agentic.core.context import RequestContext, request_context
from agentic.core.llm import Models
from agentic.services import personal_context

CASES = Path(__file__).parent / 'datasets' / 'personalization_cases.jsonl'
# Fictional athlete: every coaching fact is present except a goal.
CARD = {
    'generated_at': '2026-10-31T05:00:00+00:00', 'timezone': 'Asia/Ho_Chi_Minh', 'today': '2026-10-31',
    'profile': {'age': 29, 'sex': 'MALE'},
    'body': {'weight_kg': 68.0, 'height_cm': 172.0, 'body_fat_pct': 17.5, 'measured_at': '2026-10-30T07:00:00+07:00'},
    'goal': None,
    'athlete': {'configured': True, 'experience_level': 'INTERMEDIATE', 'primary_focus': 'HYBRID', 'available_days': 4,
                'session_minutes': 60, 'injuries': [], 'equipment': ['barbell'], 'max_hr': 190, 'resting_hr': 58,
                'resting_hr_source': 'PROFILE', 'threshold_pace_s_per_km': 300, 'recent_race': None},
    'running': {'window_weeks': 8, 'runs': 22, 'weeks_with_runs': 8, 'avg_weekly_km_4w': 18.4, 'avg_weekly_runs_4w': 3.0,
                'avg_pace_s_per_km_4w': 365, 'longest_run_km': 10.2, 'easy_share_pct': 82.0, 'pace_by_workout_type_s_per_km': {},
                'best_efforts': {'5K': {'time_seconds': 1650, 'date': '2026-10-20', 'pace_seconds_per_km': 330.0}},
                'race_predictions_seconds': {'5K': 1650, '10K': 3440},
                'last_run': {'date': '2026-10-30', 'distance_km': 6.0, 'duration_min': 36.5, 'pace_s_per_km': 365, 'workout_type': 'EASY'}},
    'training_4w': {'sessions': 14, 'sessions_by_discipline': {'RUNNING': 12, 'STRENGTH': 2}, 'acwr': 1.05, 'sessions_without_rpe': 0},
    'inventory': {'trainings_60d': 40, 'meals_14d': 30, 'body_metrics': 5, 'health_connected': False, 'health_shared_with_assistant': False},
    'missing': ['goal'],
}


def load_cases(path=CASES):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


async def route(agent, case):
    state = {'run_id': 'eval-' + case['id'], 'session_id': 'eval', 'user_id': 'eval-user', 'status': 'running',
             'messages': [HumanMessage(content=case['message'])], 'tool_outputs': [], 'tool_count': 0,
             'user_context': CARD, 'user_context_run_id': 'eval-' + case['id'], 'route_trace': []}
    started = perf_counter()
    result = await agent.decide(state)
    decision = result['decision']
    asks_known = decision['action'] == 'clarify' and any(
        personal_context.answered_by_card(field, CARD) for field in decision.get('missing_fields') or [])
    return {'id': case['id'], 'personalize': bool(decision.get('personalize')), 'topic': decision.get('topic'),
            'action': decision['action'], 'intent': decision['intent'], 'domain': decision.get('domain'),
            'router_personalize': bool(result['route_trace'][0].get('personalize')),
            'rules': [s['rule'] for s in result['route_trace'] if s['stage'] == 'rule'],
            'reads': [name for name, _ in personal_context.deep_reads(decision.get('topic') or 'general')]
            if decision.get('personalize') else [],
            'asks_known': asks_known, 'latency_ms': round((perf_counter() - started) * 1000)}


def score(case, row):
    return {'personalize_ok': row['personalize'] == case['personalize'],
            'topic_ok': not case['personalize'] or row['topic'] in case['topics'],
            'action_ok': row['action'] in case['actions'], 'no_known_questions': not row['asks_known']}


async def main(args):
    agent = OrchestrationAgent(Models(agent_settings), agent_settings)
    cases = load_cases(args.cases)
    rows = []
    token = request_context.set(RequestContext('eval-user', 'no-token', None, ()))
    try:
        for repeat in range(args.repeat):
            for case in cases:
                try:
                    row = await route(agent, case)
                except Exception as exc:  # a routing failure is a scored miss, not the end of the run
                    row = {'id': case['id'], 'error': type(exc).__name__, 'personalize': None, 'topic': None, 'action': None,
                           'asks_known': False, 'latency_ms': None}
                row.update(repeat=repeat, **score(case, row))
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        request_context.reset(token)
    personal = [r for r, c in zip(rows, cases * args.repeat) if c['personalize']]
    general = [r for r, c in zip(rows, cases * args.repeat) if not c['personalize']]
    rate = lambda items, key: round(sum(1 for r in items if r.get(key)) / len(items), 3) if items else None
    summary = {'cases': len(cases), 'repeat': args.repeat, 'runs': len(rows),
               'personalize_recall': rate(personal, 'personalize'), 'personalize_false_positive': round(
                   sum(1 for r in general if r['personalize']) / len(general), 3) if general else None,
               'router_flag_recall': rate(personal, 'router_personalize'),
               'topic_accuracy': rate(personal, 'topic_ok'), 'action_accuracy': rate(rows, 'action_ok'),
               'asks_known_facts': round(sum(1 for r in rows if r['asks_known']) / len(rows), 3),
               'errors': sum(1 for r in rows if r.get('error')),
               'latency_p50_ms': statistics.median([r['latency_ms'] for r in rows if r['latency_ms']] or [0])}
    out = Path(args.out) / f'{datetime.now():%Y%m%d-%H%M%S}'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'cases.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    print('Saved', out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', default=str(CASES))
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--out', default='eval_results/personalization')
    asyncio.run(main(parser.parse_args()))
