"""Lọc ngữ cảnh graph và nén bằng chứng đã kiểm chứng mà không sửa checkpoint."""

import json

from agentic.knowledge_graph.context.graph import ContextGraph
from agentic.knowledge_graph.context.graph import render as render_context
from agentic.knowledge_graph.service import render_lines


def model_graph_context(state):
    """Context graph của câu hỏi (nếu có) rồi thẻ tri thức tĩnh; chỉ các dòng dễ đọc, không ID hay ảnh chụp thô."""
    run = state.get("run_id")
    lines = []
    built = state.get("context_graph") if state.get("context_graph_run_id") == run else None
    usable = bool(built) and ContextGraph.model_validate(built).usable
    if built:
        lines += render_context(built)
    card = state.get("graph_context") if state.get("graph_context_run_id") == run else None
    if card:
        if usable:
            # Bản ghi cụ thể đã có trong context graph: thẻ tĩnh chỉ còn hồ sơ suy ra và ghi chú (ít token hơn).
            card = {**card, "facts": [], "episodes": []}
        lines += render_lines(card)
    return "\n".join(lines) or None


def compact_evidence(state):
    """Chỉ giữ một lần các đầu ra có thẩm quyền trong prompt; checkpoint giữ lại từng byte."""
    present = set()
    for message in state.get("messages", []):
        raw = None
        if message.type == "tool":
            raw = message.content
        elif (
            message.type == "system"
            and isinstance(message.content, str)
            and message.content.startswith("Backend đã thực thi: ")
        ):
            raw = message.content.split(": ", 1)[1]
        if isinstance(raw, str):
            try:
                present.add(json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False))
            except ValueError:
                pass
    outputs = []
    for output in state.get("tool_outputs", []):
        if json.dumps(output, sort_keys=True, ensure_ascii=False) in present:
            outputs.append(
                {
                    key: value
                    for key, value in output.items()
                    if key not in {"output", "payload", "arguments"}
                }
            )
        else:
            outputs.append(output)
    return outputs


def bounded_documents(documents, limit=18000):
    """Đúng các đoạn trích đã gửi sang tra cứu cũng là các đoạn được kiểm chứng sau đó."""
    selected = []
    remaining = limit
    for source in documents.values():
        row = {k: v for k, v in source.items() if k != "content"}
        row["content"] = source["content"][:remaining]
        remaining -= len(row["content"])
        selected.append(row)
        if remaining <= 0:
            break
    return selected
