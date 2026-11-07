"""Ghi bữa ăn không qua model chọn tool khi catalog khớp chắc chắn.

Một lượt ghi bữa ăn từng tốn 4–8 lần gọi model (tra món, đọc kết quả, dựng create_meals), trong khi các
lệnh backend chỉ mất 20–190 ms (đo trên 26 lượt ngày 02/11). Bộ định tuyến đã gọi model một lần; nó tách
luôn bản nháp `meal_log` (bữa, thời điểm, món, số lượng, đơn vị). Code tra mọi món trong một lần
list_foods, và chỉ khi mỗi món có đúng một bản ghi trùng tên chuẩn hoá (cùng tiêu chí EXACT của
/foods/resolve) với đơn vị dùng được thì mới tự dựng create_meals. Mọi trường hợp khác (món mơ hồ, thiếu
số lượng, đơn vị cần quy đổi) đi đường model như cũ, với kết quả tra cứu đã có sẵn.

Bản xem trước vẫn do backend dựng và người dùng vẫn phải xác nhận: đường nhanh chỉ bỏ bớt lời gọi model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from domains.shared.models.catalog import normalize_food_text

INTENT = "LOG_FOOD"
DOMAINS = {"meals", "foods"}
DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
# Đơn vị người dùng nói → đơn vị gốc của món mà backend tính được không cần quy đổi khẩu phần.
# "1 bát" cho món tính theo 100 g cần bảng khẩu phần của món đó: để model đọc `portions`.
COMPATIBLE = {"SERVING": {"PORTION"}, "G": {"G"}, "ML": {"ML"}}


def _moment(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo is not None else None


def complete(meal: dict) -> bool:
    """Bữa có đủ dữ kiện để code dựng: thời điểm có múi giờ và mỗi món có tên, số lượng, đơn vị."""
    items = meal.get("items") or []
    return (
        bool(items)
        and _moment(meal.get("consumed_at")) is not None
        and all(
            (item.get("food") or "").strip()
            and (item.get("quantity") or 0) > 0
            and item.get("unit") in COMPATIBLE
            for item in items
        )
    )


def eligible(state: dict) -> bool:
    decision = state.get("decision") or {}
    return (
        decision.get("intent") == INTENT
        and decision.get("action") == "tool"
        and decision.get("domain") in DOMAINS
        and not decision.get("read_only")
        and not state.get("candidate")
        and not state.get("catalog_draft")
        and not state.get("pending_action")
        and bool(decision.get("meal_log"))
    )


def next_meal(state: dict) -> tuple[int, dict] | None:
    """(vị trí, bữa) kế tiếp mà code dựng được; None thì đi đường model."""
    if not eligible(state):
        return None
    decision = state["decision"]
    index = int(decision.get("meal_log_next") or 0)
    meals = decision["meal_log"]
    if index >= len(meals) or not complete(meals[index]):
        return None
    return index, meals[index]


def continues(state: dict) -> bool:
    """Bữa trước của bản nháp vừa được lưu và còn bữa sau: tiếp tục mà không gọi lại bộ định tuyến."""
    decision = state.get("decision") or {}
    outputs = state.get("tool_outputs") or []
    last = outputs[-1] if outputs else {}
    index = int(decision.get("meal_log_next") or 0)
    return (
        decision.get("intent") == INTENT
        and 0 < index < len(decision.get("meal_log") or [])
        and last.get("tool") == "create_meals"
        and bool(last.get("ok"))
        and bool(last.get("action_id"))
        and (state.get("turn") or {}).get("run_id") == state.get("run_id")
    )


def names(meal: dict) -> list[str]:
    seen: dict[str, str] = {}
    for item in meal["items"]:
        seen.setdefault(normalize_food_text(item["food"]), item["food"].strip())
    return list(seen.values())


def _exact(query: str, unit: str, rows: list[dict]) -> dict | None:
    """Bản ghi duy nhất trùng tên chuẩn hoá mà đơn vị người dùng nói dùng được.

    Catalog có tên trùng (124/1.587 tên SYSTEM, 02/11): "Phở bò tái" có một bản theo suất và một bản theo 100 g,
    nên "1 tô" chỉ có một cách hiểu. Hai bản cùng đơn vị vẫn là mơ hồ và để model hoặc người dùng chọn."""
    key = normalize_food_text(query)
    hits = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("id")
        and key
        in {
            normalize_food_text(row.get("name_vi") or ""),
            normalize_food_text(row.get("name_en") or ""),
        }
        and row.get("serving_unit") in COMPATIBLE[unit]
    ]
    return hits[0] if len(hits) == 1 else None


def match(meal: dict, rows: Any) -> list[dict] | None:
    """Các món của create_meals khi mọi món khớp đúng một bản ghi với đơn vị dùng được; ngược lại None."""
    if not isinstance(rows, list):
        return None
    items = []
    for item in meal["items"]:
        row = _exact(item["food"], item["unit"], rows)
        if row is None:
            return None
        items.append(
            {"food_id": str(row["id"]), "quantity": item["quantity"], "unit": item["unit"]}
        )
    return items


def payload(meal: dict, items: list[dict]) -> dict:
    name = (meal.get("name") or "").strip() or ", ".join(
        item["food"].strip() for item in meal["items"]
    )
    return {
        "name": name[:120],
        "consumed_at": _moment(meal["consumed_at"]).isoformat(),
        "timezone": meal.get("timezone") or DEFAULT_TIMEZONE,
        "items": items,
    }


def instruction(meal: dict) -> str:
    """Nhiệm vụ cho đường model khi bữa kế tiếp không dựng được bằng code."""
    foods = ", ".join(
        f"{item.get('quantity') or '?'} {item.get('unit') or ''} {item.get('food')}".strip()
        for item in meal.get("items") or []
    )
    return (
        f'Ghi bữa "{meal.get("name") or "bữa ăn"}" lúc {meal.get("consumed_at") or "không rõ"}: {foods}. '
        "Tra catalog theo tên, chọn đúng món và khẩu phần rồi đề xuất create_meals."
    )
