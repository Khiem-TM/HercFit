"""Hook ghi nghiệp vụ: tích hợp phản ứng với lệnh ghi của miền bên trong cùng transaction.

Các miền gọi `emit(...)` sau khi tạo/cập nhật/xoá; tích hợp nhà cung cấp (ví
dụ bộ xuất Google Health) đăng ký hook và ghi dòng outbox trong
transaction của bên gọi, nên thay đổi nghiệp vụ và công việc lan truyền nó
cùng commit hoặc cùng không. Các miền không bao giờ import một tích hợp.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import UUID

Hook = Callable[..., Awaitable[Any]]
_hooks: list[Hook] = []


def register(hook: Hook) -> None:
    if hook not in _hooks:
        _hooks.append(hook)


async def emit(session, user_id: UUID, aggregate_type: str, entity: Any, op: str, **extra: Any) -> None:
    for hook in _hooks:
        await hook(session, user_id, aggregate_type, entity, op, **extra)
