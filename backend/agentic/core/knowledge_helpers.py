"""Code-owned KG routing policy. Graph data cannot grant tool permissions."""
import hashlib
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from schemas.progress import ProgressRead
from agentic.tools.registry import REGISTRY

TEMPLATE_ID = 'progress.explicit_dates'
TEMPLATE_VERSION = 1
TIMEZONE = 'Asia/Ho_Chi_Minh'
PILOT_DOMAINS = {'meals', 'foods', 'progress', 'metrics', 'goals'}


class FastReadPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: str
    template_id: str = TEMPLATE_ID
    template_version: int = TEMPLATE_VERSION
    registry_fingerprint: str
    tool: str = 'get_progress'
    arguments: dict[str, str]


def registry_fingerprint():
    specs = [{'name': s.name, 'domain': s.domain, 'method': s.method, 'path': s.path,
              'schema': s.schema.model_json_schema()} for _, s in sorted(REGISTRY.items())]
    return hashlib.sha256(json.dumps(specs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def latest_request(state):
    for message in reversed(state.get('messages', [])):
        if message.type == 'human':
            return message.content if isinstance(message.content, str) else ''
    return ''


def pilot_domain(message):
    text = message.casefold()
    # Only a retrieval hint: the model still makes the first routing decision.
    if re.search(r'\b(tiến độ|progress|tổng hợp|báo cáo|calo|calorie|protein)\b', text):
        return 'progress'
    if re.search(r'\b(bữa|món|ăn|meal|food|thực phẩm)\b', text):
        return 'meals'
    if re.search(r'\b(số đo|cân nặng|chiều cao)\b', text):
        return 'metrics'
    if 'mục tiêu' in text:
        return 'goals'
    return None


def make_fast_read_plan(state, now=None):
    """A full-message grammar deliberately rejects compound and implicit requests."""
    decision = state.get('decision', {})
    if (decision.get('action') != 'tool' or decision.get('next_agent') != 'tool'
            or decision.get('domain') != 'progress' or decision.get('missing_fields')
            or state.get('pending_action') or state.get('candidate') or state.get('tool_outputs')
            or state.get('tool_count', 0) or state.get('status') in {'needs_input', 'failed'}
            or not state.get('run_id')):
        return None
    text = ' '.join(latest_request(state).strip().casefold().split())
    match = re.fullmatch(r'(?:xem |cho tôi xem |kiểm tra )?tiến độ (hôm nay|hôm qua|ngày \d{4}-\d{2}-\d{2}|từ \d{4}-\d{2}-\d{2} (?:đến|tới) \d{4}-\d{2}-\d{2})[.!?]?', text)
    if not match:
        return None
    period = match[1]
    today = (now or datetime.now(ZoneInfo(TIMEZONE))).astimezone(ZoneInfo(TIMEZONE)).date()
    if period in {'hôm nay', 'hôm qua'}:
        start = end = (today - timedelta(days=period == 'hôm qua')).isoformat()
    else:
        dates = re.findall(r'\d{4}-\d{2}-\d{2}', period)
        start, end = dates[0], dates[-1]
    try:
        args = REGISTRY['get_progress'].normalize({'start_date': start, 'end_date': end, 'timezone': TIMEZONE})
    except ValueError:
        return None
    return FastReadPlan(run_id=state['run_id'], registry_fingerprint=registry_fingerprint(), arguments=args)


def verified_fast_plan(state):
    try:
        plan = FastReadPlan.model_validate(state.get('fast_read_plan'))
        fresh = make_fast_read_plan(state)
        return plan if fresh and plan == fresh else None
    except ValueError:
        return None


def terminal_progress(plan, output):
    try:
        result = ProgressRead.model_validate(output)
    except (ValueError, TypeError):
        return False
    return (result.start_date.isoformat() == plan.arguments['start_date']
            and result.end_date.isoformat() == plan.arguments['end_date']
            and result.timezone == plan.arguments['timezone']
            and len(result.days) == (result.end_date - result.start_date).days + 1
            and len({day.date for day in result.days}) == len(result.days)
            and all(result.start_date <= day.date <= result.end_date for day in result.days))


def model_graph_context(state, settings):
    if getattr(settings, 'KG_MODE', 'off') not in {'advisory', 'optimized'}:
        return None
    if state.get('graph_context_run_id') != state.get('run_id'):
        return None
    return state.get('graph_context')


def compact_evidence(state):
    """Keep authoritative outputs once in prompts; checkpoints retain every byte."""
    present = set()
    for message in state.get('messages', []):
        raw = None
        if message.type == 'tool':
            raw = message.content
        elif message.type == 'system' and isinstance(message.content, str) and message.content.startswith('Backend đã thực thi: '):
            raw = message.content.split(': ', 1)[1]
        if isinstance(raw, str):
            try:
                present.add(json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False))
            except ValueError:
                pass
    outputs = []
    for output in state.get('tool_outputs', []):
        if json.dumps(output, sort_keys=True, ensure_ascii=False) in present:
            outputs.append({key: value for key, value in output.items() if key not in {'output', 'payload', 'arguments'}})
        else:
            outputs.append(output)
    return outputs
