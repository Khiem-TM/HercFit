from agentic.prompts.registry import get_prompt
import re
from domains.catalog.models.foods import normalize_food_text
from agentic.tools.registry import REGISTRY

COACH_GUIDANCE = get_prompt('training.coach', 'v3')
CAPABILITY_GUIDANCE = get_prompt('nutrition.capabilities')
HEALTH_GUIDANCE = get_prompt('health.guidance', 'v3')

CATALOG_DEPENDENCIES = {'meals': 'foods', 'trainings': 'exercises', 'training_plans': 'exercises'}
# Các miền chỉ đọc bổ sung: huấn luyện diễn giải nhật ký/tiến độ, ghi nhật ký có thể kiểm tra lịch tập.
READ_DEPENDENCIES = {
    'coaching': ('trainings', 'progress', 'metrics', 'exercises', 'health'),
    'trainings': ('training_plans',),
    # Lịch tập treo dưới kế hoạch cha, kế hoạch cha cần id của mục tiêu đang hoạt động.
    'training_plans': ('coaching', 'goals'),
    'meals': ('progress',),
    'goals': ('progress', 'metrics', 'health'),
    # Phục hồi và vận động từ thiết bị bổ sung cho huấn luyện; câu hỏi về cơ thể so sánh với dữ liệu thiết bị.
    'progress': ('health',),
    'metrics': ('health',),
    'profile': ('health', 'metrics'),
    'health': ('metrics', 'progress'),
}


# Các tool thiết bị thô có route backend đã có bản kế nhiệm v2 (backend api/deprecations.py).
# Chúng vẫn được đăng ký (checkpoint và hành động đang chờ tham chiếu tool theo tên) nhưng
# không được cung cấp khi bộ đọc của agent đã chuyển sang context API.
SUPERSEDED_HEALTH_TOOLS = frozenset({'list_sleep_sessions', 'list_device_workouts', 'list_health_samples'})


def reader_v2_agent():
    from agentic.core.app.config import agent_settings
    return 'agent' in (agent_settings.READER_V2_DOMAINS or [])


def allowed_tools(domain):
    readable = {CATALOG_DEPENDENCIES.get(domain), *READ_DEPENDENCIES.get(domain, ())}
    hidden = SUPERSEDED_HEALTH_TOOLS if reader_v2_agent() else frozenset()
    return {
        name: spec for name, spec in REGISTRY.items()
        if name not in hidden and (spec.domain == domain or (spec.domain in readable and not spec.write))
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
# Các miền được đọc dữ liệu thiết bị nhận hướng dẫn về sức khoẻ.
HEALTH_DOMAINS = frozenset(domain for domain in ('health', *READ_DEPENDENCIES) if 'health' in (domain, *READ_DEPENDENCIES.get(domain, ())))
