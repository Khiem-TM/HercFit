"""Meal and food suggestions must be grounded in the catalog.

The router can decide to "answer" a request like "gợi ý bữa sáng nhiều protein" from general
knowledge, after which the reply model sees no tool output and may claim the catalog returned
nothing. Suggestions are therefore routed by code to one read-only catalog lookup (several
names in one list_foods call) and then answered directly from that result.
"""
import re

from agentic.agents.state import RouteDecision

INTENT = 'FOOD_SUGGESTION'
CATALOG_READS = frozenset({'list_foods', 'get_foods', 'resolve_foods'})

_SUGGEST = re.compile(r'\b(?:gợi ý|đề xuất|tư vấn|nên ăn|ăn gì|món gì|món nào|thực đơn|recommend|suggest)\b')
_FOOD = re.compile(r'\b(?:món|bữa|ăn|thực đơn|thức ăn|đồ ăn|protein|đạm|calo|kcal|breakfast|lunch|dinner|meal|food)\b')
# Logging, editing and training requests keep their own routes.
_EXCLUDE = re.compile(r'\b(?:ghi|lưu|thêm|tạo|xoá|xóa|sửa|cập nhật|nhật ký|đã ăn|bài tập|giáo án|lịch tập|kế hoạch tập)\b')

LOOKUP_INSTRUCTION = (
    'Gợi ý món: tra catalog để có món thật. Chọn 3–5 tên món hoặc nguyên liệu phổ biến hợp ngữ cảnh (bữa nào, '
    'khẩu vị; tôn trọng ăn chay/dị ứng nếu hồ sơ tri thức có) rồi gọi list_foods MỘT lần với names=[...]. '
    'Yêu cầu nhiều protein/đạm thì đặt sort=protein_density. Chỉ đọc, không ghi dữ liệu.')
ANSWER_INSTRUCTION = (
    'Gợi ý 3–5 món chỉ lấy từ kết quả list_foods của lượt này, ưu tiên món hợp ngữ cảnh. Giữ nguyên tên name_vi, '
    'không thêm tính từ. Mỗi món nêu kcal và protein kèm đúng nutrition_basis của món đó (mỗi 100 g, mỗi suất...). Tên đã tra mà '
    'không có kết quả thì nói catalog chưa có món đó. Món có portion_energy_range_kcal thì nói năng lượng tuỳ cỡ suất '
    '(ví dụ 460–800 kcal). Mẹo chung (nếu có) phải nói rõ là gợi ý chung, không có trong catalog.')


def is_food_suggestion(text):
    normalized = ' '.join((text or '').casefold().split())
    return (len(normalized) <= 300 and bool(_SUGGEST.search(normalized)) and bool(_FOOD.search(normalized))
            and not _EXCLUDE.search(normalized))


def catalog_read_this_turn(state):
    return any(o.get('tool') in CATALOG_READS and o.get('ok') for o in state.get('tool_outputs') or [])


def lookup_decision():
    return RouteDecision(intent=INTENT, action='tool', next_agent='tool', domain='foods', read_only=True,
                         instruction=LOOKUP_INSTRUCTION).model_dump()


def lookup_completed(state, result):
    """The suggestion lookup succeeded: answer from it without another routing call."""
    if (state.get('decision') or {}).get('intent') != INTENT or result.get('pending_action'):
        return False
    if result.get('status') not in (None, 'running'):
        return False
    outputs = result.get('tool_outputs') or []
    return bool(outputs) and outputs[-1].get('tool') in CATALOG_READS and bool(outputs[-1].get('ok'))
