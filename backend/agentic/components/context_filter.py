"""Lọc ngữ cảnh graph và nén bằng chứng đã kiểm chứng mà không sửa checkpoint."""

import json

from agentic.knowledge_graph.service import render_lines


def model_graph_context(state):
    if state.get("graph_context_run_id") != state.get("run_id") or not state.get("graph_context"):
        return None
    # Chỉ các dòng dễ đọc: không ID, phiên bản, khả năng tĩnh hay ảnh chụp thô.
    return "\n".join(render_lines(state["graph_context"])) or None


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
