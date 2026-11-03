"""Người dùng sửa lệnh ghi lịch tập ngay trên thẻ xác nhận.

Payload đã sửa đi qua đúng các bước của một lệnh mới: schema của tool, chạy thử trên backend (bản xem trước),
rồi thay payload và hash của chính hành động đang chờ. Lệnh vẫn chỉ được thực thi bằng API xác nhận có cấu trúc
và Store.authorize; danh tính tài nguyên và version mong đợi được giữ từ đề xuất gốc.
"""
import json

from fastapi import HTTPException
from pydantic import ValidationError

from agentic.core.context import request_context
from agentic.services.memory.store import payload_hash
from agentic.tools.integrations.backend_client import BackendError
from agentic.tools.registry import PREVIEW_PATHS, REGISTRY

EDITABLE_TOOLS = frozenset({'create_training_plans', 'update_training_plans'})
PINNED = ('resource_id', 'expected_version_id')


async def revise(action: dict, edited: dict) -> tuple[dict, dict]:
    """Trả về (các trường mới của hành động, bản xem trước của backend) hoặc ném 422."""
    tool = action['tool']
    if tool not in EDITABLE_TOOLS:
        raise HTTPException(422, 'This action cannot be edited')
    original = action.get('payload') or {}
    try:
        normalized = REGISTRY[tool].normalize({**edited, **{key: original[key] for key in PINNED if key in original}})
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, f'Lịch tập đã sửa chưa hợp lệ: {exc}') from None
    ctx = request_context.get()
    body = {key: value for key, value in normalized.items() if key != 'resource_id'}
    try:
        display = await ctx.backend.request('POST', PREVIEW_PATHS[tool].format(resource_id=normalized.get('resource_id')),
                                            ctx.token, body=body)
    except BackendError as exc:
        raise HTTPException(exc.status if exc.status < 500 else 502, exc.detail) from None
    changes = {'payload': normalized, 'payload_hash': payload_hash(tool, normalized),
               'preview': tool + '\n' + json.dumps(normalized, ensure_ascii=False, indent=2)}
    return changes, display
