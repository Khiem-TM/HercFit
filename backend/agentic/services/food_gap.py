"""Món ăn chưa có trong catalog: thẻ "Tìm món / Tạo món riêng" do code dựng, thay cho tra cứu web.

Ghi bữa ăn chỉ dùng bản ghi catalog thật. Món người dùng nói mà không trùng tên chuẩn hoá (name_vi/name_en) với bản ghi
nào thì HercFit không đoán món gần giống và không tra web: câu trả lời do code viết báo catalog chưa có món, kèm thẻ để
người dùng tìm trong catalog (GET /api/foods?search=) hoặc tạo món riêng (POST /api/foods; nút gợi ý điền 4 chỉ số qua
/chat/food-nutrition). Thẻ gửi lại lựa chọn có cấu trúc (`food_choices`: key → food_id, lượng, đơn vị) ở lượt kế tiếp;
code dựng create_meals từ đó và người dùng vẫn xác nhận trên thẻ xác nhận như mọi lệnh ghi.
"""
from __future__ import annotations

from typing import Any

from agentic.agents.state import RouteDecision
from agentic.services import meal_logging
from domains.shared.models.catalog import normalize_food_text

INTENT = meal_logging.INTENT
MAX_ITEMS = 5
# Lượt tra catalog mà một lần tìm rỗng nghĩa là "catalog chưa có món cần ghi" (không phải lượt chỉ đọc hay gợi ý món).
LOGGING_INTENTS = {INTENT, 'catalog_lookup'}
DEFAULT_INSTRUCTION = 'Ghi bữa ăn theo yêu cầu gốc của người dùng.'


def _names(row: dict) -> set[str]:
    return {normalize_food_text(row.get('name_vi') or ''), normalize_food_text(row.get('name_en') or '')} - {''}


def missing(meal: dict, index: int, rows: Any, resolved: dict | None = None) -> list[dict]:
    """Các món của bữa không trùng tên bản ghi nào (bất kể đơn vị) mà người dùng chưa chọn trên thẻ."""
    resolved = resolved or {}
    known = set()
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            known |= _names(row)
    gaps = []
    for position, item in enumerate(meal.get('items') or []):
        key = meal_logging.item_key(index, position)
        if key not in resolved and normalize_food_text(item.get('food') or '') not in known:
            gaps.append(gap_item(key, item.get('food'), item.get('quantity'), item.get('unit')))
    return gaps


def gap_item(key: str, query: Any, quantity: Any = None, unit: Any = None) -> dict:
    return {'key': key, 'query': str(query or '').strip()[:80], 'quantity': quantity, 'unit': unit}


def usable(row: Any, unit: str) -> bool:
    """Bản ghi người dùng chọn tính được với đơn vị thẻ gửi (cùng bảng COMPATIBLE của đường nhanh)."""
    return isinstance(row, dict) and bool(row.get('id')) and row.get('serving_unit') in meal_logging.COMPATIBLE.get(unit, ())


def card(items: list[dict], *, meal_log: list | None = None, index: int = 0, instruction: str | None = None,
         resolved: dict | None = None) -> dict:
    """State của thẻ: các món thiếu (key, tên, lượng nháp) và bản nháp bữa để dựng lại create_meals sau khi chọn."""
    meal_log = list(meal_log or [])
    meal = meal_log[index] if index < len(meal_log) else None
    return {'items': items[:MAX_ITEMS], 'meal_log': meal_log, 'meal_index': index,
            'meal': {k: meal.get(k) for k in ('name', 'consumed_at')} if meal else None,
            'resolved': dict(resolved or {}), 'instruction': instruction or DEFAULT_INSTRUCTION}


def reply(items: list[dict], retry: bool = False) -> str:
    names = ', '.join(f'"{item["query"]}"' for item in items)
    if retry:
        return (f'Món đã chọn cho {names} không dùng được (không tìm thấy hoặc sai đơn vị). '
                'Bạn chọn lại hoặc tạo món riêng bên dưới.')
    return (f'Danh mục món ăn của HercFit chưa có {names}. Bạn tìm món tương tự trong danh mục hoặc tạo món riêng '
            'bên dưới; HercFit sẽ ghi bữa sau khi bạn chọn.')


def ask(items: list[dict], retry: bool = False, **draft) -> dict:
    """Kết quả của bước dừng lại hỏi bằng thẻ: câu trả lời do code viết, node trả lời đặt trạng thái needs_input."""
    gap = card(items, **draft)
    return {'status': 'running', 'error': None, 'food_gap': gap, 'prepared_reply': reply(gap['items'], retry)}


def picks_only(state: dict) -> bool:
    """Lựa chọn trên thẻ không kèm bản nháp bữa của router: đọc bản ghi đã chọn rồi để model dựng create_meals."""
    decision = state.get('decision') or {}
    return (decision.get('intent') == INTENT and decision.get('action') == 'tool' and decision.get('domain') in meal_logging.DOMAINS
            and not decision.get('read_only') and not decision.get('meal_log') and bool(decision.get('food_resolved'))
            and not state.get('candidate') and not state.get('pending_action'))


def from_empty_search(state: dict, result: dict) -> dict | None:
    """Model chọn tool vừa tìm list_foods(search) và catalog trả rỗng ở lượt ghi bữa: hỏi bằng thẻ thay vì tra web."""
    decision = state.get('decision') or {}
    if (decision.get('read_only') or decision.get('intent') not in LOGGING_INTENTS or result.get('pending_action')
            or result.get('food_gap') or result.get('status') not in {'running', 'needs_input'}):
        return None
    new = (result.get('tool_outputs') or [])[len(state.get('tool_outputs') or []):]
    empty = [o for o in new if o.get('tool') == 'list_foods' and o.get('ok') and o.get('output') == []
             and ((o.get('arguments') or {}).get('search') or '').strip()]
    if not empty:
        return None
    query = empty[-1]['arguments']['search']
    instruction = decision.get('instruction') if decision.get('intent') == INTENT else None
    return ask([gap_item('q:0', query)], instruction=instruction)


def carried(previous: dict) -> dict | None:
    """Thẻ của lượt trước, chỉ khi lượt đó dừng lại hỏi bằng chính thẻ này."""
    gap = previous.get('food_gap')
    return gap if previous.get('status') == 'needs_input' and gap and gap.get('items') else None


def apply(state: dict) -> dict | None:
    """Quyết định do code cho lựa chọn trên thẻ; None khi tin nhắn không mang lựa chọn cho thẻ đang mở."""
    gap, choices = state.get('food_gap'), state.get('food_choices')
    if not gap or not choices:
        return None
    queries = {item['key']: item['query'] for item in gap['items']}
    chosen = {}
    for choice in choices:
        if choice.get('key') in queries:
            chosen[choice['key']] = {'food_id': str(choice['food_id']), 'quantity': choice['quantity'],
                                     'unit': choice['unit'], 'query': queries[choice['key']]}
    if not chosen:
        return None
    resolved = {**(gap.get('resolved') or {}), **chosen}
    instruction = gap.get('instruction') or DEFAULT_INSTRUCTION
    if not gap.get('meal_log'):
        # Không có bản nháp bữa của router: model dựng create_meals; bản ghi đã chọn được đọc trước bằng get_foods.
        instruction += ' Món người dùng đã chọn trên thẻ (dùng đúng bản ghi get_foods của lượt này): ' + '; '.join(
            f'"{c["query"]}": {c["quantity"]:g} {c["unit"]}' for c in resolved.values()) + '.'
    decision = RouteDecision(intent=INTENT, action='tool', next_agent='tool', domain='meals', instruction=instruction,
                             meal_log=gap.get('meal_log') or []).model_dump()
    decision.update(meal_log_next=gap.get('meal_index') or 0, food_resolved=resolved)
    return {'decision': decision, 'food_gap': None, 'food_choices': None, 'status': 'running', 'error': None}
