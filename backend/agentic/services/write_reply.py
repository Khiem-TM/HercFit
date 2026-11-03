"""Câu trả lời do code viết sau các lệnh ghi đã xác nhận: những gì backend đã lưu, từ chính bản ghi nó trả về.

Sau một lệnh ghi đã duyệt, router từng gửi lượt quay lại bước tool, nơi model viết văn bản
thay vì lời gọi ("Bữa ăn đã được tạo bản ghi (đang chờ xác nhận qua API riêng)", lượt chạy 433a847a, 3725845a,
6cdf6905, 2446b7af). Văn bản đó thành câu hỏi của lượt, và một bản ghi đã lưu bị báo là vẫn đang chờ.
Vì vậy lượt đã lưu thứ gì đó kết thúc bằng bản tóm tắt này, chỉ dựng từ output của các tool đã thực thi.
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
# Các lệnh ghi không có chi tiết đáng liệt kê, theo cách người dùng sẽ gọi tên chúng.
DONE = {
    'update_meals': 'Đã cập nhật bữa ăn', 'delete_meals': 'Đã xoá bữa ăn khỏi nhật ký',
    'update_trainings': 'Đã cập nhật buổi tập', 'delete_trainings': 'Đã xoá buổi tập khỏi nhật ký',
    'update_metrics': 'Đã cập nhật số đo', 'delete_metrics': 'Đã xoá số đo',
    'update_goals': 'Đã cập nhật mục tiêu', 'delete_goals': 'Đã xoá mục tiêu',
    'complete_goal': 'Đã đánh dấu hoàn thành mục tiêu', 'cancel_goal': 'Đã huỷ mục tiêu',
    'update_profile': 'Đã cập nhật hồ sơ', 'merge_personal_info': 'Đã cập nhật thông tin cá nhân',
    'onboard': 'Đã lưu hồ sơ ban đầu', 'update_training_profile': 'Đã cập nhật hồ sơ vận động viên',
    'update_sport_session': 'Đã cập nhật buổi thể thao trên Google Health',
    'delete_sport_session': 'Đã xoá buổi thể thao khỏi Google Health',
    'delete_water': 'Đã xoá lần uống nước khỏi Google Health',
}
# Google chưa trả điểm vừa ghi (Operation chưa xong): lần đồng bộ sau mang nó về.
ARRIVES_LATER = ' (Google đã nhận; số liệu hiện sau lần đồng bộ tới)'
# Câu trả lời vẫn gọi lệnh ghi đã lưu là bản xem trước đang chờ xác nhận (đã bỏ dấu).
PENDING_CLAIM = re.compile(r'cho (?:ban )?xac nhan|xac nhan qua api|api rieng|ban xem truoc|chua (?:duoc )?luu|'
                           r'trang thai cho|chua chinh thuc')


def executed_writes(state) -> list[dict]:
    """Output tool của các lệnh ghi mà backend đã thực thi trong lượt này (sau khi người dùng xác nhận)."""
    return [output for output in (state or {}).get('tool_outputs') or []
            if output.get('ok') and output.get('action_id') and getattr(REGISTRY.get(output.get('tool') or ''), 'write', False)]


# Lệnh ghi catalog (món/bài tập mới) thường mở đường cho một lệnh ghi nhật ký: sau nó router vẫn quyết định bước tiếp.
CATALOG_WRITES = frozenset({'create_foods', 'finalize_foods', 'create_exercises', 'finalize_exercises'})
# Mục tiêu (đã bỏ dấu) của router: bước ghi, bước chỉ chuẩn bị cho lệnh ghi, và bước cần đọc thêm sau khi ghi.
WRITE_OBJECTIVE = re.compile(r'\b(?:ghi|tao|luu|ket thuc|cap nhat|sua|xoa|them|dat|thay|create|log|record|save|end|update|delete|add)\b')
PREPARE_OBJECTIVE = re.compile(r'^(?:tra|tim|xem truoc|preview|xac nhan|chuan bi|kiem tra|lookup|search|find|resolve)\b')
READ_OBJECTIVE = re.compile(r'con lai|tien do|so sanh|phan tich|goi y|tu van|\bdoc\b|get_|targets|progress|remaining')


def finishes_turn(state) -> bool:
    """Lệnh ghi vừa thực thi đã hoàn tất yêu cầu: kết thúc lượt bằng biên nhận do code viết, không gọi lại router.

    Sau mỗi lần xác nhận, router và thường cả model tool từng được gọi lại chỉ để kết luận "đã xong", tốn 2–22 s
    (19 lượt duyệt: p50 5,2 s, max 110 s; phần ghi chỉ ~0,1 s). Chỉ áp dụng khi chắc chắn: lệnh ghi cuối không phải
    lệnh catalog, không mục tiêu nào cần đọc thêm, và số lệnh ghi đã thực thi kể từ quyết định của router đủ cho các
    mục tiêu ghi của nó. Mọi trường hợp khác (nhiều buổi tập, ghi xong rồi hỏi calo còn lại...) vẫn đi qua router.
    """
    outputs = (state or {}).get('tool_outputs') or []
    decision = (state or {}).get('decision') or {}
    writes = executed_writes(state)
    if not outputs or not writes or outputs[-1] is not writes[-1] or outputs[-1]['tool'] in CATALOG_WRITES:
        return False
    if not isinstance(decision.get('writes_before'), int):
        return False  # quyết định không phải của router (hoặc checkpoint cũ): giữ đường cũ
    objectives = [normalize_food_text(str(item)) for item in decision.get('objectives') or []]
    if any(READ_OBJECTIVE.search(item) for item in objectives):
        return False
    needed = sum(1 for item in objectives if WRITE_OBJECTIVE.search(item) and not PREPARE_OBJECTIVE.match(item))
    return len(writes) - decision['writes_before'] >= max(1, needed)


def reads_after_writes(state) -> bool:
    """Lượt đã đọc thêm dữ liệu sau lệnh ghi cuối, ví dụ lượng calo còn lại hôm nay sau khi ghi một bữa ăn."""
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
    """1104.5 -> "1.104,5" (nhóm chữ số và dấu phẩy thập phân kiểu Việt Nam)."""
    number = _number(value)
    if number is None:
        return '—'
    text = f'{number:,.{digits}f}'.rstrip('0').rstrip('.') if digits else f'{number:,.0f}'
    return text.replace(',', ' ').replace('.', ',').replace(' ', '.')


def when(value, timezone: str | None = None) -> str:
    """"14:37 01/11/2026" theo múi giờ riêng của bản ghi."""
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


def sport_lines(record: dict) -> list[str]:
    derived, value = record.get('derived') or {}, record.get('value') or {}
    name = value.get('displayName') or 'buổi thể thao'
    moment = when(record.get('start_at'))
    facts = [f'{vn(_number(derived.get("duration_seconds")) / 60, 0)} phút' if _number(derived.get('duration_seconds')) else '',
             f'{vn(_number(derived.get("distance_m")) / 1000, 2)} km' if _number(derived.get('distance_m')) else '',
             f'~{vn(derived.get("energy_kcal"), 0)} kcal' if _number(derived.get('energy_kcal')) is not None else '']
    facts = [fact for fact in facts if fact]
    return [f'✅ Đã ghi buổi **{name}** lên Google Health' + (f' lúc {moment}' if moment else '')
            + (': ' + ' · '.join(facts) if facts else '') + (ARRIVES_LATER if record.get('pending') else '')]


def water_lines(record: dict) -> list[str]:
    amount = _number((record.get('derived') or {}).get('amount_ml'))
    moment = when(record.get('start_at'))
    return ['✅ Đã ghi' + (f' {vn(amount, 0)} ml' if amount is not None else '') + ' nước uống lên Google Health'
            + (f' lúc {moment}' if moment else '') + (ARRIVES_LATER if record.get('pending') else '')]


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
    if tool == 'log_sport_session':
        return sport_lines(record)
    if tool == 'log_water':
        return water_lines(record)
    if tool in {'create_foods', 'finalize_foods', 'create_exercises', 'finalize_exercises'}:
        return catalog_lines(tool, record)
    if tool in {'create_plan', 'create_training_plans', 'update_training_plans', 'end_training_plan'}:
        return plan_lines(tool, record)
    return ['✅ ' + DONE.get(tool, 'Đã lưu thay đổi')]


def write_reply(state) -> str:
    """Những gì lượt này đã lưu, mỗi lệnh ghi đã thực thi một khối; '' khi không lưu gì."""
    writes = executed_writes(state)
    blocks = ['\n'.join(lines_for(output)) for output in writes]
    meals = [_number((output.get('output') or {}).get('energy_kcal')) for output in writes if output['tool'] == 'create_meals']
    if len(meals) > 1 and all(value is not None for value in meals):
        blocks.append(f'Tổng các bữa vừa lưu: **{vn(sum(meals))} kcal**.')
    return '\n\n'.join(blocks)


def _quantity(value) -> str:
    """"1" và "1.000000" của backend là cùng một lượng."""
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
    """Lệnh ghi mới có lặp lại một lệnh lượt này đã thực thi không: cùng các món của bữa ăn, cùng thời điểm bắt đầu buổi tập
    và bài tập, cùng số đo hay cùng tên catalog (tên bữa ăn diễn đạt khác vẫn là cùng bữa ăn)."""
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
