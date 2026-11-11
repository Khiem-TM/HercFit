"""G_C: kết quả của f, cùng cách dựng nó thành các dòng gọn cho prompt."""

from typing import Any, Literal

from pydantic import BaseModel, Field

# Ngân sách prompt của G_C (byte UTF-8, là cận trên an toàn của số token tiếng Việt).
BUDGET = 2400
GRAIN = {"day": "ngày", "week": "tuần", "month": "tháng"}


class ContextGraph(BaseModel):
    status: Literal["ok", "empty", "rejected", "timeout", "unavailable", "blocked", "skipped"] = (
        "skipped"
    )
    # Nguồn của truy vấn: mẫu viết tay, mẫu đã học, sinh mới trong lượt này.
    source: Literal["seed", "learned", "generated", "none"] = "none"
    template: str | None = None
    fingerprint: str | None = None
    timeframe: dict[str, Any] | None = None
    # Graph đã chiếu hết các lệnh ghi của người dùng chưa (cổng read-your-writes).
    synced: bool = True
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    nodes: int = 0
    edges: int = 0
    error: str | None = None
    attempts: int = 0
    duration_ms: float = 0.0
    # Chỉ cho vết và đánh giá; không bao giờ vào prompt.
    cypher: str | None = None

    @property
    def usable(self):
        """Đủ để trả lời một câu hỏi đọc mà không gọi backend."""
        return self.status in {"ok", "empty"} and self.synced


def _value(value):
    if isinstance(value, dict):
        label = value.get("_label") or value.get("_type")
        inner = ", ".join(f"{k}={_value(v)}" for k, v in value.items() if not k.startswith("_"))
        return f"{label}({inner})" if label else "{" + inner + "}"
    if isinstance(value, list):
        return "[" + "; ".join(_value(v) for v in value if v not in (None, "", [])) + "]"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def render(graph):
    """Dòng đầu nêu phạm vi, độ hạt và trạng thái đồng bộ; mỗi dòng sau là một hàng kết quả."""
    data = graph.model_dump() if isinstance(graph, ContextGraph) else graph
    if data.get("status") not in {"ok", "empty"}:
        return []
    frame = data.get("timeframe") or {}
    header = " · ".join(
        filter(
            None,
            [
                "Context graph (truy vấn trên dữ liệu đã lưu)",
                f"phạm vi {frame.get('start')} → {frame.get('end')} (theo {GRAIN.get(frame.get('grain'), '')})"
                if frame
                else None,
                "đồng bộ với database"
                if data.get("synced", True)
                else "CHƯA đồng bộ: thiếu lệnh ghi mới nhất",
                f"{len(data.get('rows') or [])} dòng"
                if data.get("rows")
                else "không có dữ liệu trong phạm vi",
            ],
        )
    )
    lines = [header]
    used = len(header.encode())
    columns = data.get("columns") or []
    for row in data.get("rows") or []:
        if len(columns) == 1:
            line = "- " + _value(row[0])
        else:
            line = "- " + " · ".join(
                f"{column}={_value(value)}"
                for column, value in zip(columns, row)
                if value not in (None, "", [])
            )
        size = len(line.encode()) + 1
        if used + size > BUDGET:
            lines.append("- … (cắt bớt theo ngân sách)")
            break
        lines.append(line)
        used += size
    return lines


def summary(graph):
    """Nhãn và số đếm cho telemetry của lượt; không có giá trị dữ liệu nào."""
    data = graph.model_dump() if isinstance(graph, ContextGraph) else graph
    if not data:
        return None
    return {
        "status": data.get("status"),
        "source": data.get("source"),
        "template": data.get("template"),
        "rows": len(data.get("rows") or []),
        "nodes": data.get("nodes", 0),
        "edges": data.get("edges", 0),
        "synced": data.get("synced"),
        "error": data.get("error"),
        "attempts": data.get("attempts", 0),
        "grain": (data.get("timeframe") or {}).get("grain"),
        "basis": (data.get("timeframe") or {}).get("basis"),
        "duration_ms": data.get("duration_ms"),
    }
