"""Conservative JEV read routing; all writes keep the existing orchestration path."""
import math
import re
from models.foods import normalize_food_text
from agentic.services.routing import latest_request
from agentic.prompts.v1.routing import JEV_READ_ROUTES
from agentic.prompts.registry import get_questions

JEV_ROUTING_QUESTIONS = get_questions("routing.jev")

def jev_routing_projection(state):
    """Keep the candidate gate cheap; history and personal snapshots never leave it."""
    decision = state.get('decision') or {}
    if (state.get('tool_outputs') or state.get('tool_count') or state.get('pending_action')
            or state.get('candidate') or state.get('catalog_handoff') or state.get('research_handoff')
            or state.get('research_count') or state.get('research_work') or state.get('research_answer')
            or decision.get('objectives') or decision.get('read_only')
            or ((state.get('turn') or {}).get('run_id') == state.get('run_id') and state.get('turn'))):
        return None
    text = latest_request(state).strip()
    normalized = normalize_food_text(text)
    # Clear writes, compound requests, pronoun follow-ups, and explicit research
    # take the baseline path without paying for another classification call.
    if not text or re.search(
            r'\b(?:ghi|them|tao|luu|xoa|sua|cap nhat|dang ky|dat lich|len lich|len ke hoach|thiet ke|'
            r'add|create|save|delete|remove|update|record|change|replace|cancel|complete|'
            r'va|dong thoi|sau do|roi|kem|and|also|then|'
            r'mon do|bai do|cai do|nhu tren|nhu cu|vua roi|tiep tuc|no|again|it|that|those|same|continue|'
            r'web|internet|nghien cuu|nguon ben ngoai|research|online)\b', normalized):
        return None
    # Defense in depth before the service's identity-aware redaction. Do not
    # include user/session/run IDs, profile fields, backend credentials, or history.
    text = re.sub(r'(?i)\bBearer\s+\S+', '[credential]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email]', text)
    text = re.sub(r'(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '[identifier]', text)
    text = re.sub(r'(?<!\w)(?:\+?\d[\s().-]*){10,15}(?!\w)', '[phone]', text)
    return {'request': text, 'task': 'standalone_read', 'has_pending_action': False}


def jev_read_domain(evaluation):
    if evaluation.get('status') != 'ok':
        return None
    answers = evaluation.get('answers') or {}
    route = answers.get('route') or {}
    confidence = route.get('confidence')
    if (route.get('choice') not in JEV_READ_ROUTES or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool) or not math.isfinite(confidence) or not 0.9 <= confidence <= 1):
        return None
    for name in ('mutation', 'multiple', 'dependency', 'web'):
        probability = (answers.get(name) or {}).get('noul')
        if (not isinstance(probability, (int, float)) or isinstance(probability, bool)
                or not math.isfinite(probability) or not 0 <= probability <= 0.1):
            return None
    return route['choice']
