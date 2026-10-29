"""Code-owned KG routing policy. Graph data cannot grant tool permissions."""
from agentic.components.context_filter import compact_evidence, model_graph_context
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from schemas.progress import ProgressRead
from agentic.tools.registry import REGISTRY

TEMPLATE_ID = 'progress.explicit_dates'
TEMPLATE_VERSION = 1
TIMEZONE = 'Asia/Ho_Chi_Minh'


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


def fast_reads_enabled(settings):
    # The progress template parses the request itself; it does not read graph data.
    return getattr(settings, 'FAST_READ_ENABLED', False) or getattr(settings, 'KG_MODE', 'off') == 'optimized'


def _progress_arguments(match, today):
    period = match[1]
    if period in {'hôm nay', 'hôm qua'}:
        start = end = (today - timedelta(days=period == 'hôm qua')).isoformat()
    else:
        dates = re.findall(r'\d{4}-\d{2}-\d{2}', period)
        start, end = dates[0], dates[-1]
    return {'start_date': start, 'end_date': end, 'timezone': TIMEZONE}


def _no_arguments(_match, _today):
    return {}


def _timezone_argument(_match, _today):
    return {'timezone': TIMEZONE}


@dataclass(frozen=True)
class FastTemplate:
    """A full-message grammar for one standalone read. Compound or implicit
    requests never match, so the LLM router still handles everything else."""
    id: str
    version: int
    domain: str
    tool: str
    pattern: re.Pattern
    instruction: str
    arguments: Callable = _no_arguments


_LEAD = r'(?:xem |cho tôi xem |cho mình xem |kiểm tra |tra )?'
_OWNER = r'(?: của (?:tôi|mình|em))?'
FAST_TEMPLATES = (
    FastTemplate(TEMPLATE_ID, TEMPLATE_VERSION, 'progress', 'get_progress',
                 re.compile(_LEAD + r'tiến độ (hôm nay|hôm qua|ngày \d{4}-\d{2}-\d{2}|từ \d{4}-\d{2}-\d{2} (?:đến|tới) \d{4}-\d{2}-\d{2})[.!?]?'),
                 'Trả lời yêu cầu tiến độ theo kết quả backend đã xác minh.', _progress_arguments),
    FastTemplate('goals.current', 1, 'goals', 'current_goal',
                 re.compile(_LEAD + r'mục tiêu(?: hiện tại| đang thực hiện)?' + _OWNER + r'(?: là gì| thế nào)?[.!?]?'),
                 'Trả lời về mục tiêu hiện tại theo kết quả backend đã xác minh; không có bản ghi nghĩa là chưa đặt mục tiêu.'),
    FastTemplate('metrics.latest', 1, 'metrics', 'latest_metrics',
                 re.compile(_LEAD + r'(?:cân nặng|số đo|chỉ số cơ thể)(?: hiện tại| mới nhất| gần nhất| gần đây)?' + _OWNER
                            + r'(?: là bao nhiêu| bao nhiêu)?[.!?]?'),
                 'Trả lời số đo mới nhất theo kết quả backend đã xác minh; không có bản ghi nghĩa là chưa ghi số đo.'),
    FastTemplate('profile.read', 1, 'profile', 'get_profile',
                 re.compile(_LEAD + r'hồ sơ(?: cá nhân)?' + _OWNER + r'[.!?]?'),
                 'Tóm tắt hồ sơ theo kết quả backend đã xác minh.'),
    FastTemplate('nutrition.targets', 1, 'progress', 'get_nutrition_targets',
                 re.compile(r'(?:(?:mỗi ngày|một ngày|hôm nay) )?(?:(?:tôi|mình|em) )?(?:cần|nên|được|còn được|còn) (?:ăn )?(?:bao nhiêu|mấy) (?:calo|kcal)'
                            r'(?: mỗi ngày| một ngày| hôm nay| nữa)?[.!?]?|' + _LEAD + r'mục tiêu (?:calo|kcal|dinh dưỡng|năng lượng)(?: hôm nay| mỗi ngày)?[.!?]?'),
                 'Trả lời mục tiêu năng lượng và macro, phần calo còn lại hôm nay theo kết quả backend đã xác minh; '
                 'nêu ngắn gọn cách tính (BMR, TDEE) và cảnh báo nếu có. Thiếu dữ liệu hồ sơ thì nêu trường còn thiếu.',
                 _timezone_argument),
)
TEMPLATES_BY_ID = {template.id: template for template in FAST_TEMPLATES}


def _normalized_request(state):
    return ' '.join(latest_request(state).strip().casefold().split())


def make_fast_read_plan(state, now=None):
    """A full-message grammar deliberately rejects compound and implicit requests."""
    decision = state.get('decision', {})
    if (decision.get('action') != 'tool' or decision.get('next_agent') != 'tool'
            or decision.get('missing_fields')
            or state.get('pending_action') or state.get('candidate') or state.get('tool_outputs')
            or state.get('tool_count', 0) or state.get('status') in {'needs_input', 'failed'}
            or not state.get('run_id')):
        return None
    text = _normalized_request(state)
    today = (now or datetime.now(ZoneInfo(TIMEZONE))).astimezone(ZoneInfo(TIMEZONE)).date()
    for template in FAST_TEMPLATES:
        if template.domain != decision.get('domain'):
            continue
        match = template.pattern.fullmatch(text)
        if not match:
            continue
        try:
            args = REGISTRY[template.tool].normalize(template.arguments(match, today))
        except ValueError:
            return None
        return FastReadPlan(run_id=state['run_id'], template_id=template.id, template_version=template.version,
                            registry_fingerprint=registry_fingerprint(), tool=template.tool, arguments=args)
    return None


def fast_route(state, now=None):
    """Code-owned routing for standalone reads: returns (decision, plan) or None.

    Applies only to the first routing step of a run with no pending work, so a
    follow-up, compound request or unfinished workflow always reaches the LLM router.
    """
    if (state.get('tool_outputs') or state.get('tool_count') or state.get('pending_action') or state.get('candidate')
            or state.get('catalog_handoff') or state.get('research_handoff') or state.get('research_count')
            or state.get('status') in {'needs_input', 'failed'} or not state.get('run_id')
            or ((state.get('turn') or {}).get('run_id') == state.get('run_id'))):
        return None
    text = _normalized_request(state)
    for template in FAST_TEMPLATES:
        if not template.pattern.fullmatch(text):
            continue
        from agentic.agents.state import RouteDecision
        decision = RouteDecision(intent='READ', action='tool', next_agent='tool', domain=template.domain,
                                 read_only=True, instruction=template.instruction).model_dump()
        plan = make_fast_read_plan({**state, 'decision': decision}, now=now)
        return (decision, plan) if plan else None
    return None


def verified_fast_plan(state):
    try:
        plan = FastReadPlan.model_validate(state.get('fast_read_plan'))
        fresh = make_fast_read_plan(state)
        return plan if fresh and plan == fresh else None
    except ValueError:
        return None


def terminal_result(plan, output):
    """Whether one fast read fully answers its template (no further routing needed)."""
    if plan.template_id == TEMPLATE_ID:
        return terminal_progress(plan, output)
    return True  # Single-record reads are complete when the call succeeded (404 = no record).


def fast_answer_instruction(plan):
    template = TEMPLATES_BY_ID.get(plan.template_id)
    return template.instruction if template else 'Trả lời theo kết quả backend đã xác minh.'


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
