"""Bộ nhớ quyết định: nhớ lượt hội thoại bằng các quyết định (tool đã gọi, tham số có cấu trúc, kết quả, người dùng
duyệt/sửa/từ chối) thay vì toàn bộ văn bản.

Tham số chỉ giữ các khoá có cấu trúc trong ARG_KEYS (ngày, khoảng, số lượng, đơn vị), không bao giờ văn bản tự do hay
ID. Kết quả là một dòng gọn dựng từ bản ghi backend trả về. Vết của phiên được đọc từ nhật ký SQL
(agent_turn_records, agent_execution_records), nguồn có thẩm quyền và commit cùng checkpoint; graph chiếu cùng dữ liệu
đó thành Run-[:NEXT]->Run-[:HAS_EXECUTION]->Execution cho Cypher.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from agentic.knowledge_graph.intents import label as intent_label

LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")
ARG_KEYS = frozenset(
    {
        "start_date",
        "end_date",
        "date",
        "days",
        "limit",
        "quantity",
        "unit",
        "consumed_at",
        "started_at",
        "recorded_at",
        "weight_kg",
        "timezone",
    }
)
NAME_KEYS = ("name", "title", "display_name", "name_vi")
AMOUNTS = (("energy_kcal", "kcal"), ("protein_g", "g protein"), ("weight_kg", "kg"))
DECISIONS = {"approved": "đã duyệt", "rejected": "đã từ chối", "pending": "chờ xác nhận"}
STATUSES = {
    "completed": "xong",
    "needs_input": "chờ bổ sung",
    "pending_confirmation": "chờ xác nhận",
    "failed": "lỗi",
}


def remembered_args(args):
    kept = {
        key: value
        for key, value in (args or {}).items()
        if key in ARG_KEYS and isinstance(value, (str, int, float, bool)) and key != "timezone"
    }
    return ", ".join(f"{key}={value}" for key, value in sorted(kept.items()))[:200] or None


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def outcome(data):
    """Một dòng gọn về kết quả backend: số bản ghi, hoặc tên + món + năng lượng của bản ghi vừa đọc/ghi."""
    value = data.get("record", data) if isinstance(data, dict) else data
    if isinstance(value, list):
        return f"{len(value)} bản ghi"
    if not isinstance(value, dict):
        return None
    if (
        isinstance(value.get("items"), list)
        and "total" in value
        and not any(k in value for k in NAME_KEYS)
    ):
        return f"{value.get('total')} bản ghi"
    parts = [next((value[k] for k in NAME_KEYS if value.get(k)), None)]
    names = []
    for item in (value.get("items") or [])[:4]:
        if not isinstance(item, dict):
            continue
        snapshot = item.get("food_snapshot") or item.get("exercise_snapshot") or {}
        name = snapshot.get("name_vi") or snapshot.get("name_en")
        quantity = _number(item.get("quantity"))
        if name:
            names.append(
                f"{name} {quantity:g}{(item.get('unit') or '').lower()}" if quantity else name
            )
    parts.append(", ".join(names) or None)
    for key, unit in AMOUNTS:
        amount = _number(value.get(key))
        if amount is not None:
            parts.append(f"{round(amount, 1):g} {unit}")
    return " · ".join(str(part) for part in parts if part)[:160] or None


def render(rows):
    """Các lượt gần nhất của phiên (cũ trước), mỗi lượt một dòng: giờ · ý định · trạng thái · các bước."""
    lines = []
    for row in reversed(rows):
        data = row["data"] or {}
        moment = row["occurred_at"]
        clock = moment.astimezone(LOCAL).strftime("%H:%M") if isinstance(moment, datetime) else ""
        steps = []
        for execution in row["executions"] or []:
            step = execution.get("tool") or "?"
            if execution.get("args"):
                step += f"({execution['args']})"
            if execution.get("status") == "failed":
                step += " → lỗi"
            elif execution.get("outcome"):
                step += " → " + execution["outcome"]
            steps.append(step)
        state = DECISIONS.get(data.get("decision")) or STATUSES.get(
            data.get("status"), data.get("status")
        )
        if data.get("edited_fields"):
            state = f"{state} (sửa {', '.join(data['edited_fields'])})"
        lines.append(
            " · ".join(
                filter(None, [clock, intent_label(data.get("intent")), state, "; ".join(steps)])
            )
        )
    return lines
