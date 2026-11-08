from agentic.prompts.registry import get_prompt
import re
from domains.catalog.models.foods import normalize_food_text
from agentic.tools.registry import REGISTRY

COACH_GUIDANCE = get_prompt('training.coach', 'v5')
CAPABILITY_GUIDANCE = get_prompt('nutrition.capabilities')
HEALTH_GUIDANCE = get_prompt('health.guidance', 'v5')

CATALOG_DEPENDENCIES = {'meals': 'foods', 'trainings': 'exercises', 'training_plans': 'exercises'}
# Các miền chỉ đọc bổ sung: huấn luyện diễn giải nhật ký/tiến độ, ghi nhật ký có thể kiểm tra lịch tập.
READ_DEPENDENCIES = {
    'coaching': ('trainings', 'progress', 'metrics', 'exercises', 'health'),
    'trainings': ('training_plans',),
    # Lịch tập gắn với mục tiêu đang hoạt động; huấn luyện đọc nhật ký để điều chỉnh lịch.
    'training_plans': ('coaching', 'goals'),
    'meals': ('progress',),
    'goals': ('progress', 'metrics', 'health'),
    # Phục hồi và vận động từ thiết bị bổ sung cho huấn luyện; câu hỏi về cơ thể so sánh với dữ liệu thiết bị.
    'progress': ('health',),
    'metrics': ('health',),
    'profile': ('health', 'metrics'),
    'health': ('metrics', 'progress'),
}


def allowed_tools(domain):
    readable = {CATALOG_DEPENDENCIES.get(domain), *READ_DEPENDENCIES.get(domain, ())}
    return {
        name: spec for name, spec in REGISTRY.items()
        if spec.domain == domain or (spec.domain in readable and not spec.write)
    }


# Yêu cầu sửa/xoá một bản ghi đã có (không dấu). Chỉ khi đó tool update_/delete_ mới được bind ở chế độ ghi nhanh.
EDIT_REQUEST = re.compile(r'\b(?:sua|xoa|cap nhat|chinh lai|huy|nham|ghi lai|doi lai|doi thanh|'
                          r'update|delete|edit|remove|change|fix|undo)\b')


def logging_tools(allowed, domain, request):
    """Chế độ ghi nhanh: chỉ tool của chính miền và catalog nó phụ thuộc; tool sửa/xoá chỉ khi yêu cầu nói tới.

    Schema của các tool ghi buổi tập rất lớn (create/update_trainings, log/update_sport_session mỗi cái 7–9k ký tự),
    nên bỏ các tool không dùng tới giảm đáng kể token và lựa chọn nhiễu của model."""
    edits = bool(EDIT_REQUEST.search(normalize_food_text(request or '')))
    keep = {domain, CATALOG_DEPENDENCIES.get(domain)}
    return {name: spec for name, spec in allowed.items()
            if spec.domain in keep and (edits or not name.startswith(('update_', 'delete_')))}


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
