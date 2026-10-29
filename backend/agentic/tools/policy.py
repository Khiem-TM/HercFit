from agentic.prompts.registry import get_prompt
import re
from models.foods import normalize_food_text
from agentic.tools.registry import REGISTRY

COACH_GUIDANCE = get_prompt('training.coach')
CAPABILITY_GUIDANCE = get_prompt('nutrition.capabilities')

CATALOG_DEPENDENCIES = {'meals': 'foods', 'trainings': 'exercises', 'training_plans': 'exercises'}
# Additional read-only domains: coaching interprets logs/progress, logging may check the schedule.
READ_DEPENDENCIES = {
    'coaching': ('trainings', 'progress', 'metrics', 'exercises'),
    'trainings': ('training_plans',),
    'training_plans': ('coaching',),
    'meals': ('progress',),
    'goals': ('progress', 'metrics'),
}


def allowed_tools(domain):
    readable = {CATALOG_DEPENDENCIES.get(domain), *READ_DEPENDENCIES.get(domain, ())}
    return {
        name: spec for name, spec in REGISTRY.items()
        if spec.domain == domain or (spec.domain in readable and not spec.write)
    }


def needs_catalog_handoff(domain, text):
    if domain not in CATALOG_DEPENDENCIES:
        return False
    normalized = normalize_food_text(text)
    return bool(re.search(r'food[_ ]?id|exercise[_ ]?id|\bid\s+(?:food|exercise|mon|thuc pham|bai tap)|khong.*(?:cong cu|catalog)|khong the.*tra cuu', normalized))


def continue_catalog_lookup(state):
    dependency = CATALOG_DEPENDENCIES.get(state.get('decision', {}).get('domain'))
    if not dependency or state.get('status') != 'running' or state.get('catalog_handoff'):
        return False
    outputs = state.get('tool_outputs') or []
    if not outputs:
        return False
    last = outputs[-1]
    spec = REGISTRY.get(last.get('tool'))
    if not spec or spec.domain != dependency or spec.write or not last.get('ok'):
        return False
    data = last.get('output')
    if last['tool'].startswith('resolve_'):
        return isinstance(data, dict) and data.get('status') == 'EXACT'
    return bool(data)


TRAINING_DOMAINS = frozenset({'trainings', 'training_plans', 'coaching'})
