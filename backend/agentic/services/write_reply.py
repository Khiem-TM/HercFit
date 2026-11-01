"""Code-owned reply after confirmed writes: what the backend saved, from the records it returned.

After an approved write the router used to send the turn back to the tool step, where the model wrote prose
instead of a call ("Bữa ăn đã được tạo bản ghi (đang chờ xác nhận qua API riêng)", runs 433a847a, 3725845a,
6cdf6905, 2446b7af). The prose became the turn's question, and a saved record was reported as still pending.
A turn that saved something therefore ends with this summary, built only from executed tool outputs.
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from agentic.tools.registry import REGISTRY
from domains.catalog.models.foods import normalize_food_text

TIMEZONE = 'Asia/Ho_Chi_Minh'
UNITS = {'G': 'g', 'ML': 'ml', 'SERVING': 'suất'}
INTENSITY = {'LIGHT': 'nhẹ', 'MODERATE': 'vừa', 'VIGOROUS': 'mạnh'}
# Writes without details worth listing, as the user would name them.
DONE = {
    'update_meals': 'Đã cập nhật bữa ăn', 'delete_meals': 'Đã xoá bữa ăn khỏi nhật ký',
    'update_trainings': 'Đã cập nhật buổi tập', 'delete_trainings': 'Đã xoá buổi tập khỏi nhật ký',
    'update_metrics': 'Đã cập nhật số đo', 'delete_metrics': 'Đã xoá số đo',
    'update_goals': 'Đã cập nhật mục tiêu', 'delete_goals': 'Đã xoá mục tiêu',
    'complete_goal': 'Đã đánh dấu hoàn thành mục tiêu', 'cancel_goal': 'Đã huỷ mục tiêu',
    'update_profile': 'Đã cập nhật hồ sơ', 'merge_personal_info': 'Đã cập nhật thông tin cá nhân',
    'onboard': 'Đã lưu hồ sơ ban đầu', 'update_training_profile': 'Đã cập nhật hồ sơ vận động viên',
}
# A reply that still calls the saved write a preview waiting for confirmation (accents stripped).
PENDING_CLAIM = re.compile(r'cho (?:ban )?xac nhan|xac nhan qua api|api rieng|ban xem truoc|chua (?:duoc )?luu|'
                           r'trang thai cho|chua chinh thuc')


def executed_writes(state) -> list[dict]:
    """Tool outputs of the writes the backend executed in this turn (after the user's confirmation)."""
    return [output for output in (state or {}).get('tool_outputs') or []
            if output.get('ok') and output.get('action_id') and getattr(REGISTRY.get(output.get('tool') or ''), 'write', False)]


def reads_after_writes(state) -> bool:
    """The turn read more data after its last write, e.g. today's remaining calories after logging a meal."""
    outputs = (state or {}).get('tool_outputs') or []
    last = max((i for i, output in enumerate(outputs) if output in executed_writes(state)), default=None)
    return last is not None and any(output.get('ok') and not output.get('action_id') and not getattr(
        REGISTRY.get(output.get('tool') or ''), 'write', True) for output in outputs[last + 1:])


def claims_pending(text: str) -> bool:
    return bool(PENDING_CLAIM.search(normalize_food_text(text or '')))


def _number(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def vn(value, digits: int = 1) -> str:
    """1104.5 -> "1.104,5" (Vietnamese grouping and decimal comma)."""
    number = _number(value)
    if number is None:
        return '—'
    text = f'{number:,.{digits}f}'.rstrip('0').rstrip('.') if digits else f'{number:,.0f}'
    return text.replace(',', ' ').replace('.', ',').replace(' ', '.')


def when(value, timezone: str | None = None) -> str:
    """"14:37 01/11/2026" in the record's own time zone."""
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(ZoneInfo(timezone or TIMEZONE))
    except (ValueError, TypeError, KeyError):
        return ''
    return moment.strftime('%H:%M %d/%m/%Y')


def day(value) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        return str(value or '')


def macros(record: dict) -> str:
    parts = [f'{label} {vn(record.get(key))} g' for label, key in (('P', 'protein_g'), ('C', 'carbohydrate_g'), ('F', 'fat_g'))
             if _number(record.get(key)) is not None]
    return ' · '.join(parts)


def meal_lines(record: dict) -> list[str]:
    energy = _number(record.get('energy_kcal'))
    head = f'✅ Đã lưu bữa ăn **{record.get("name") or "bữa ăn"}**'
    moment = when(record.get('consumed_at'), record.get('timezone'))
    head += f' lúc {moment}' if moment else ''
    head += f': **{vn(energy)} kcal**' if energy is not None else ''
    head += f' ({macros(record)})' if macros(record) else ''
    lines = [head]
    for item in record.get('items') or []:
        food = item.get('food_snapshot') or {}
        quantity = f'{vn(item.get("quantity"), 2)} {UNITS.get(item.get("unit"), item.get("unit") or "")}'.strip()
        kcal = _number(item.get('energy_kcal'))
        lines.append(f'- {food.get("name_vi") or "Món ăn"}: {quantity}' + (f' → {vn(kcal)} kcal' if kcal is not None else ''))
    if record.get('nutrition_incomplete'):
        lines.append('Một số món thiếu dữ liệu dinh dưỡng trong catalog; tổng chưa tính phần đó.')
    return lines


def training_item(item: dict) -> str:
    name = (item.get('exercise_snapshot') or {}).get('name_vi') or 'Bài tập'
    performance = item.get('performance') or {}
    details = []
    if item.get('kind') == 'STRENGTH':
        sets = performance.get('sets') or []
        if sets:
            details.append(f'{len(sets)} hiệp')
        if _number(item.get('volume_kg')):
            details.append(f'volume {vn(item.get("volume_kg"), 0)} kg')
    else:
        distance = _number(item.get('distance_meters') or performance.get('distance_meters'))
        if distance:
            details.append(f'{vn(distance / 1000, 2)} km')
        seconds = _number(item.get('duration_seconds') or performance.get('duration_seconds'))
        if seconds:
            details.append(f'{vn(seconds / 60, 0)} phút')
        if performance.get('intensity') in INTENSITY:
            details.append('cường độ ' + INTENSITY[performance['intensity']])
    return f'- {name}' + (': ' + ', '.join(details) if details else '')


def training_lines(record: dict) -> list[str]:
    head = f'✅ Đã lưu buổi tập **{record.get("name") or "buổi tập"}**'
    moment = when(record.get('started_at'), record.get('timezone'))
    head += f' lúc {moment}' if moment else ''
    facts = []
    seconds = _number(record.get('duration_seconds'))
    if seconds:
        facts.append(f'{vn(seconds / 60, 0)} phút')
    energy = _number(record.get('energy_kcal'))
    if energy is not None:
        facts.append(f'~{vn(energy, 0)} kcal')
    if _number(record.get('training_load')) is not None:
        facts.append(f'tải {vn(record.get("training_load"), 0)}')
    head += (': ' + ' · '.join(facts)) if facts else ''
    return [head, *(training_item(item) for item in record.get('items') or [])]


def metric_lines(record: dict) -> list[str]:
    parts = [f'{label} {vn(record.get(key))} {unit}' for label, key, unit in (
        ('cân nặng', 'weight_kg', 'kg'), ('chiều cao', 'height_cm', 'cm'), ('mỡ', 'body_fat_pct', '%'), ('cơ', 'muscle_mass_kg', 'kg'))
        if _number(record.get(key)) is not None]
    moment = when(record.get('recorded_at'))
    return ['✅ Đã lưu số đo' + (f' lúc {moment}' if moment else '') + (': ' + ' · '.join(parts) if parts else '')]


def goal_lines(record: dict) -> list[str]:
    span = ' → '.join(filter(None, (day(record.get('start_date')) if record.get('start_date') else '',
                                    day(record.get('target_date')) if record.get('target_date') else '')))
    return [f'✅ Đã lưu mục tiêu **{record.get("title") or "mục tiêu"}**' + (f' ({span})' if span else '')]


def catalog_lines(tool: str, record: dict) -> list[str]:
    name = record.get('name_vi') or record.get('name') or ''
    if tool.endswith('_exercises'):
        return [f'✅ Đã thêm bài tập **{name}** vào catalog của bạn']
    energy = _number(record.get('energy_kcal'))
    basis = 'suất' if record.get('serving_unit') == 'PORTION' else f'{vn(record.get("serving_size"), 0)} {UNITS.get(record.get("serving_unit"), "g")}'
    return [f'✅ Đã thêm món **{name}** vào catalog của bạn' + (f' ({vn(energy)} kcal / {basis})' if energy is not None else '')]


def plan_lines(tool: str, record: dict) -> list[str]:
    name = record.get('name') or 'lịch tập'
    span = ' → '.join(day(record.get(key)) for key in ('start_date', 'end_date') if record.get(key))
    if tool == 'create_plan':
        return [f'✅ Đã tạo kế hoạch **{name}**' + (f' ({span})' if span else '')]
    if tool == 'end_training_plan':
        return [f'✅ Đã kết thúc lịch tập **{name}**']
    entries = [entry for entry in record.get('entries') or [] if not entry.get('is_rest')]
    detail = ', '.join(filter(None, (f'{len(entries)} buổi tập' if entries else '', span)))
    return [f'✅ Đã lưu lịch tập **{name}**' + (f': {detail}' if detail else '')]


def lines_for(output: dict) -> list[str]:
    tool, record = output['tool'], output.get('output') if isinstance(output.get('output'), dict) else {}
    if tool == 'create_meals':
        return meal_lines(record)
    if tool == 'create_trainings':
        return training_lines(record)
    if tool == 'create_metrics':
        return metric_lines(record)
    if tool == 'create_goals':
        return goal_lines(record)
    if tool in {'create_foods', 'finalize_foods', 'create_exercises', 'finalize_exercises'}:
        return catalog_lines(tool, record)
    if tool in {'create_plan', 'create_training_plans', 'update_training_plans', 'end_training_plan'}:
        return plan_lines(tool, record)
    return ['✅ ' + DONE.get(tool, 'Đã lưu thay đổi')]


def write_reply(state) -> str:
    """What this turn saved, one block per executed write; '' when it saved nothing."""
    writes = executed_writes(state)
    blocks = ['\n'.join(lines_for(output)) for output in writes]
    meals = [_number((output.get('output') or {}).get('energy_kcal')) for output in writes if output['tool'] == 'create_meals']
    if len(meals) > 1 and all(value is not None for value in meals):
        blocks.append(f'Tổng các bữa vừa lưu: **{vn(sum(meals))} kcal**.')
    return '\n\n'.join(blocks)


def _quantity(value) -> str:
    """"1" and the backend's "1.000000" are the same quantity."""
    number = _number(value)
    return '' if number is None else format(number.normalize(), 'f')


def _items(payload: dict, key: str) -> list[tuple]:
    return sorted((str(item.get(key)), _quantity(item.get('quantity')), str(item.get('unit') or ''))
                  for item in payload.get('items') or [] if isinstance(item, dict))


def _minute(value) -> str:
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M')
    except (ValueError, TypeError):
        return ''


def repeats_write(state, name: str, payload: dict) -> bool:
    """Whether a new write call repeats one this turn already executed: the same meal items, the same session
    start and exercises, the same measurement or the same catalog name (a reworded meal name is still the same meal)."""
    for output in executed_writes(state):
        record = output.get('output') if isinstance(output.get('output'), dict) else {}
        if output['tool'] != name or not record:
            continue
        if name == 'create_meals' and _items(payload, 'food_id') == _items(record, 'food_id'):
            return True
        if name == 'create_trainings':
            exercises = sorted(str(item.get('exercise_id')) for item in payload.get('items') or [])
            if exercises == sorted(str(item.get('exercise_id')) for item in record.get('items') or []) and (
                    not payload.get('started_at') or _minute(payload['started_at']) == _minute(record.get('started_at'))):
                return True
        if name == 'create_metrics' and _number(payload.get('weight_kg')) == _number(record.get('weight_kg')) and (
                not payload.get('recorded_at') or _minute(payload['recorded_at']) == _minute(record.get('recorded_at'))):
            return True
        if name in {'create_foods', 'create_exercises', 'create_goals', 'create_plan'}:
            key = 'title' if name == 'create_goals' else 'name' if name == 'create_plan' else 'name_vi'
            if normalize_food_text(str(payload.get(key) or '')) == normalize_food_text(str(record.get(key) or '')):
                return True
    return False
