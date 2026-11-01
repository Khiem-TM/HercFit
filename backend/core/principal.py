"""Ai đang đọc: người dùng, hay trợ lý hành động thay người dùng.

Phụ thuộc xác thực đặt principal cho request. Các lần đọc dữ liệu sức khoẻ
trong miền hỏi `current()` thay vì xem header, nên quyết định
"trợ lý có được thấy điều này không?" ở mọi nơi chỉ có một đầu vào.

* USER: một access token bình thường.
* AGENT: token uỷ quyền mà backend cấp cho service agent sau khi nó
  chứng minh danh tính (POST /api/v2/auth/delegations). Trong giai đoạn chuyển tiếp, token người dùng
  mang header tự khai báo `X-HercFit-Client: agent` cũng được
  coi là AGENT (không bao giờ có nhiều quyền hơn người dùng); khi bật
  settings.AGENT_DELEGATION_REQUIRED thì các token đó bị từ chối.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

AGENT_CLIENT_HEADER = "x-hercfit-client"


class PrincipalKind(StrEnum):
    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    user_id: UUID
    delegated: bool = False           # True chỉ với token uỷ quyền do backend cấp
    consent_version: int | None = None  # phiên bản consent thấy được lúc cấp uỷ quyền

    @property
    def is_agent(self) -> bool:
        return self.kind is PrincipalKind.AGENT


_current: ContextVar[Principal | None] = ContextVar("hercfit_principal", default=None)


def set_current(principal: Principal | None):
    return _current.set(principal)


def reset(token) -> None:
    _current.reset(token)


def current() -> Principal | None:
    return _current.get()


def is_agent() -> bool:
    principal = _current.get()
    return principal is not None and principal.is_agent
