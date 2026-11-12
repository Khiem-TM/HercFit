"""Lệnh ghi đơn giản nhận diện bằng code: cân nặng, nước uống, giấc ngủ theo mẫu rõ ràng.

Một tin nhắn như "cân nặng 68,2 kg" từng tốn một lần gọi model định tuyến và một lần gọi tool model chỉ để dựng một
lệnh ghi một trường. Ở đây ngữ pháp khớp trên TOÀN BỘ tin nhắn đã chuẩn hoá (cùng cách với fast_route): tin nhắn có
thêm ý khác, có dấu hỏi hay từ điều kiện ("nếu", "cần", "muốn", "bao nhiêu") không khớp và đi đường router như cũ.
Lời gọi dựng sẵn vẫn đi qua ToolAgent.execute_calls: danh sách cho phép của miền, bản xem trước và thẻ xác nhận.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from agentic.agents.state import RouteDecision
from agentic.services.routing import _normalized_request

TIMEZONE = "Asia/Ho_Chi_Minh"
CONDITIONAL = re.compile(r"\?|\b(?:nếu|cần|muốn|bao nhiêu)\b")
_NUM = r"(\d+(?:[.,]\d+)?)"
_WHO = r"(?:(?:tôi|mình|em) )?"
_WHEN = r"(?:(?:sáng nay|hôm nay|tối nay|trưa nay|chiều nay|vừa xong|vừa|mới) )?"
WEIGHT = re.compile(rf"{_WHEN}{_WHO}{_WHEN}(?:cân nặng|cân|nặng)(?: là| hiện tại)? {_NUM} ?kg[.!]?")
WATER = re.compile(
    rf"{_WHO}{_WHEN}uống(?: (?:1|một) (?:ly|cốc|chai) nước)? {_NUM} ?(ml|l|lít)(?: nước)?[.!]?"
)
_CLOCK = r"(\d{1,2}) ?(?:h|:|giờ) ?(\d{2})?(?: ?phút)?"
SLEEP = re.compile(
    rf"{_WHO}(?:(?:đêm qua|tối qua|hôm qua) )?{_WHO}ngủ (?:từ |lúc )?{_CLOCK} (?:đến|tới|-) (?:lúc )?{_CLOCK}(?: sáng)?[.!]?"
)


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def _weight(match):
    kg = _number(match.group(1))
    return ("metrics", "LOG_METRICS", "create_metrics", {"weight_kg": kg}) if 20 <= kg <= 400 else None


def _water(match):
    amount, unit = _number(match.group(1)), match.group(2)
    ml = amount * 1000 if unit in {"l", "lít"} else amount
    return ("meals", "LOG_WATER", "log_water", {"amount_ml": ml, "timezone": TIMEZONE}) if 0 < ml <= 5000 else None


def _sleep(match, now):
    """Đêm gần nhất có giờ thức dậy đã qua: giờ đi ngủ lùi một ngày khi nó muộn hơn giờ thức (qua nửa đêm)."""
    bed_h, bed_m, wake_h, wake_m = (int(value or 0) for value in match.groups())
    if bed_h > 23 or wake_h > 23 or bed_m > 59 or wake_m > 59:
        return None
    zone = ZoneInfo(TIMEZONE)
    local = now.astimezone(zone)
    wake = datetime.combine(local.date(), time(wake_h, wake_m), zone)
    if wake > local:
        wake -= timedelta(days=1)
    bed = datetime.combine(wake.date(), time(bed_h, bed_m), zone)
    if bed >= wake:
        bed -= timedelta(days=1)
    return ("metrics", "LOG_SLEEP", "log_sleep",
            {"started_at": bed.isoformat(), "ended_at": wake.isoformat(), "timezone": TIMEZONE})


def recognize(text: str, now: datetime | None = None) -> tuple[str, str, str, dict] | None:
    """(miền, intent, tool, tham số) khi cả tin nhắn là một lệnh ghi đơn giản; ngược lại None."""
    if not text or CONDITIONAL.search(text):
        return None
    now = now or datetime.now(ZoneInfo(TIMEZONE))
    if match := WEIGHT.fullmatch(text):
        return _weight(match)
    if match := WATER.fullmatch(text):
        return _water(match)
    if match := SLEEP.fullmatch(text):
        return _sleep(match, now)
    return None


def simple_route(state, now=None) -> dict | None:
    """Quyết định do code cho lệnh ghi đơn giản ở bước định tuyến đầu tiên của lượt (cùng điều kiện với fast_route);
    lời gọi dựng sẵn nằm trong decision["code_call"] để agent chuyên trách thực thi."""
    if (
        state.get("tool_outputs")
        or state.get("tool_count")
        or state.get("pending_action")
        or state.get("candidate")
        or state.get("status") in {"needs_input", "failed"}
        or not state.get("run_id")
        or ((state.get("turn") or {}).get("run_id") == state.get("run_id"))
    ):
        return None
    found = recognize(_normalized_request(state), now)
    if found is None:
        return None
    domain, intent, tool, args = found
    decision = RouteDecision(intent=intent, action="tool", next_agent="tool", domain=domain,
                             instruction=f"Đề xuất {tool} đã dựng sẵn để người dùng xác nhận.").model_dump()
    return {**decision, "code_call": {"name": tool, "args": args}}
