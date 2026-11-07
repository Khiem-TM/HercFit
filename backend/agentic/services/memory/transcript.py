"""Hàm hỗ trợ bản ghi phiên: hàm thuần, không gọi Redis hay model.

Một lượt phản chiếu những gì lịch sử chat hiển thị: tin nhắn người dùng của lượt chạy và các
câu trả lời của orchestration_agent sau nó. Lời gọi tool, kết quả tool và ghi chú
hệ thống chỉ nằm trong checkpoint.
"""

import json

from agentic.tools.registry import REGISTRY

AGENT = "orchestration_agent"
# Các bản ghi đáng nhớ theo tên; báo cáo và phân tích thì được tính lại.
ENTITY_DOMAINS = {"metrics", "goals", "meals", "trainings", "foods", "exercises", "training_plans"}
NAME_FIELDS = ("name_vi", "name", "title", "name_en")
TIME_FIELDS = ("consumed_at", "started_at", "recorded_at", "start_date")
LIST_ENTITIES = 3
GAP_MESSAGE_CHARS = 500
TITLE_CHARS = 60
LAST_MESSAGE_CHARS = 90


def visible(messages):
    """Những gì người dùng thấy: tin nhắn của chính họ và câu trả lời cuối của agent."""
    return [m for m in messages or [] if m.type == "human" or getattr(m, "name", None) == AGENT]


def _message(message):
    content = (
        message.content
        if isinstance(message.content, str)
        else json.dumps(message.content, ensure_ascii=False)
    )
    return {
        "id": message.id,
        "role": message.type,
        "name": getattr(message, "name", None),
        "content": content,
    }


def turn_from_state(values):
    """Lượt của lượt chạy này: tin nhắn người dùng cuối cùng và các câu trả lời theo sau."""
    messages = visible(values.get("messages"))
    start = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].type == "human"), None)
    if not values.get("run_id") or start is None:
        return None
    return {
        "run_id": values["run_id"],
        "status": values.get("status"),
        "messages": [_message(m) for m in messages[start:]],
    }


def seed_turns(values):
    """Chia cửa sổ checkpoint thành các lượt; chỉ lượt mới nhất có run ID đã biết."""
    turns = []
    for message in visible(values.get("messages")):
        if message.type == "human" or not turns:
            turns.append(
                {
                    "run_id": f"legacy:{message.id or len(turns)}",
                    "status": "completed",
                    "messages": [],
                }
            )
        turns[-1]["messages"].append(_message(message))
    if turns and values.get("run_id") and turns[-1]["messages"][0]["role"] == "human":
        turns[-1].update(run_id=values["run_id"], status=values.get("status"))
    return turns


def _records(output):
    data = output.get("output")
    if isinstance(data, dict) and isinstance(data.get("record"), dict):
        data = data["record"]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)][:LIST_ENTITIES]
    return [data] if isinstance(data, dict) else []


def entities_from_state(values):
    """Các bản ghi mà lượt chạy đã đọc hoặc ghi, mới nhất trước. ID chỉ lấy từ output của backend."""
    found = []
    for output in reversed(values.get("tool_outputs") or []):
        spec = REGISTRY.get(output.get("tool") or "")
        # Bản ghi đã xoá không phải thứ để tham chiếu lại.
        if (
            not output.get("ok")
            or spec is None
            or spec.domain not in ENTITY_DOMAINS
            or spec.method == "DELETE"
        ):
            continue
        for record in _records(output):
            if record.get("id"):
                found.append(
                    {
                        "kind": spec.domain,
                        "id": str(record["id"]),
                        "name": next((str(record[k]) for k in NAME_FIELDS if record.get(k)), None),
                        "at": next((str(record[k]) for k in TIME_FIELDS if record.get(k)), None),
                    }
                )
    return found


def merge_entities(previous, current, seq, limit):
    merged, seen = [], set()
    for entity in [*({**item, "seq": seq} for item in current), *previous]:
        key = (entity.get("kind"), entity.get("id"))
        if key not in seen:
            seen.add(key)
            merged.append(entity)
    return merged[:limit]


def outside_messages(message_count, covered, window):
    """Các tin nhắn chưa được tóm tắt và không nằm trong cửa sổ nguyên văn."""
    return max(0, message_count - covered - window)


def gap_turns(turns, outside):
    """Các lượt chưa tóm tắt cũ nhất có ít nhất một tin nhắn nằm ngoài cửa sổ."""
    selected = []
    for turn in turns:
        if outside <= 0:
            break
        selected.append(turn)
        outside -= len(turn["messages"])
    return selected


def fold_plan(turns, outside, max_chars):
    """Các lượt chưa tóm tắt cũ nhất nằm hoàn toàn ngoài cửa sổ, trong một ngân sách prompt."""
    selected, used = [], 0
    for turn in turns:
        size = sum(len(m["content"]) for m in turn["messages"])
        if len(turn["messages"]) > outside or (selected and used + size > max_chars):
            break
        selected.append(turn)
        outside -= len(turn["messages"])
        used += size
    return selected


def _clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def render_memory(summary, gap, entities, limit):
    """Một khối có giới hạn. Khi cắt bớt thì bỏ bản ghi trước, rồi các lượt gần đây, rồi bản tóm tắt."""
    sections = []
    if summary:
        sections.append("Tóm tắt các lượt trước:\n" + summary.strip())
    if gap:
        lines = [
            "- "
            + ("Người dùng" if m["role"] == "human" else "Trợ lý")
            + ": "
            + _clip(m["content"], GAP_MESSAGE_CHARS)
            for turn in gap
            for m in turn["messages"]
        ]
        sections.append("Các lượt trước chưa được tóm tắt:\n" + "\n".join(lines))
    if entities:
        lines = [
            "- "
            + " · ".join(
                part
                for part in (e.get("kind"), e.get("name"), e.get("at"), "id=" + str(e.get("id")))
                if part
            )
            for e in entities
        ]
        sections.append(
            "Bản ghi đã nhắc trong phiên (ID nội bộ để tra cứu, không hiển thị cho người dùng):\n"
            + "\n".join(lines)
        )
    text = "\n\n".join(sections)
    return text if len(text) <= limit else text[:limit] + "…(rút gọn)"
