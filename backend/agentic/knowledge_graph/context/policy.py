"""Lớp chính sách thứ ba (sau validator và transaction chỉ đọc): kiểm tra từng giá trị Neo4j trả về.

Mọi nút trả về phải thuộc người dùng (hoặc là dữ liệu hệ thống / công khai), chưa bị xoá, và Run/Execution phải thuộc
một phiên còn sống. Vi phạm làm hỏng cả kết quả: không trả nửa vời. Chỉ thuộc tính trong lược đồ được giữ lại.
"""

from datetime import date, datetime

from neo4j.graph import Node, Path, Relationship
from neo4j.time import Date, DateTime, Duration, Time

from ..schema import LABELS, LOCAL, REL_PROPS, SESSION_SCOPED


class PolicyViolation(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _label(node):
    known = [name for name in node.labels if name in LABELS]
    if len(known) != 1:
        raise PolicyViolation("unknown_label")
    return known[0]


def check_node(node, owner, sessions):
    label = _label(node)
    scope = LABELS[label].scope
    props = dict(node)
    if scope == "private":
        if props.get("owner_id") != owner or props.get("deleted") is not False:
            raise PolicyViolation("foreign_or_deleted_node")
    elif scope == "mixed":
        if not (props.get("owner_id") == owner or props.get("scope") == "SYSTEM"):
            raise PolicyViolation("foreign_catalog_node")
    if label in SESSION_SCOPED and props.get("session_id") not in sessions:
        raise PolicyViolation("closed_session")
    return label


def plain(value, owner, sessions, stats):
    """Giá trị JSON được của một ô kết quả; nút và quan hệ chỉ còn thuộc tính trong lược đồ."""
    if isinstance(value, Node):
        label = check_node(value, owner, sessions)
        stats["nodes"].add(value.element_id)
        props = {
            k: plain(v, owner, sessions, stats)
            for k, v in value.items()
            if k in LABELS[label].props
        }
        return {"_label": label, **{k: v for k, v in props.items() if v is not None}}
    if isinstance(value, Relationship):
        for end in (value.start_node, value.end_node):
            if end is not None and end.labels:
                check_node(end, owner, sessions)
        stats["edges"].add(value.element_id)
        allowed = REL_PROPS.get(value.type, {})
        props = {k: plain(v, owner, sessions, stats) for k, v in value.items() if k in allowed}
        return {"_type": value.type, **{k: v for k, v in props.items() if v is not None}}
    if isinstance(value, Path):
        raise PolicyViolation("path")
    if isinstance(value, DateTime):
        return value.to_native().astimezone(LOCAL).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, datetime):
        return value.astimezone(LOCAL).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, (Date, date)):
        return value.iso_format() if isinstance(value, Date) else value.isoformat()
    if isinstance(value, (Duration, Time)):
        return str(value)
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, list):
        return [plain(item, owner, sessions, stats) for item in value]
    if isinstance(value, dict):
        return {k: plain(v, owner, sessions, stats) for k, v in value.items()}
    return value
