"""Các cổng (port) mà miền health-records cần từ tích hợp nhà cung cấp.

Code nghiệp vụ không được import package của nhà cung cấp. Tích hợp nhà cung cấp
đăng ký một bản cài đặt lúc import (integrations/google_health/directory.py);
khi không có, mọi người dùng đơn giản là không có liên kết nhà cung cấp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ProviderStatus:
    provider: str
    status: str                       # ACTIVE, NEEDS_REAUTH, REVOKED, ERROR
    provider_profile: dict[str, Any] = field(default_factory=dict)
    last_success_at: datetime | None = None
    # Múi giờ nhà cung cấp báo cho tài khoản (Google settings.timeZone); None khi chưa biết.
    timezone: str | None = None

    @property
    def connected(self) -> bool:
        return self.status in {"ACTIVE", "NEEDS_REAUTH"}


@dataclass(frozen=True)
class TypeAvailability:
    """Theo từng loại dữ liệu: người dùng đã cấp, HercFit đọc loại này, và đã đồng bộ khoảng ngày nào."""
    granted: bool
    enabled: bool
    complete_through: Any = None
    complete_from: Any = None


class ProviderDirectory(Protocol):
    async def status(self, session: AsyncSession, user_id: UUID) -> ProviderStatus | None: ...

    async def availability(self, session: AsyncSession, user_id: UUID) -> dict[str, TypeAvailability]: ...

    async def linked_trainings(self, session: AsyncSession, user_id: UUID) -> set[UUID]:
        """Buổi gym đã gắn vào một phiên mà đồng hồ ghi (kcal của nó tính theo phiên đó)."""

    async def write(self, session: AsyncSession, user_id: UUID, kind: str, payload: dict[str, Any] | None = None,
                    point_id: UUID | None = None, delete: bool = False) -> dict[str, Any] | None:
        """Ghi xuyên qua lên nhà cung cấp (cân nặng, chiều cao, mỡ...); None khi chưa kết nối."""

    async def refresh(self, user_id: UUID, days: int = 2) -> bool:
        """Đồng bộ ngay `days` ngày gần nhất từ nhà cung cấp; True khi lần đọc thành công."""

    async def before_account_erasure(self, session: AsyncSession, user_id: UUID) -> None:
        """Thu hồi quyền tại nhà cung cấp (cố gắng hết mức) trước khi xoá dòng tài khoản."""


_directories: list[ProviderDirectory] = []


def register(directory: ProviderDirectory) -> None:
    if all(type(existing) is not type(directory) for existing in _directories):
        _directories.append(directory)


async def provider_status(session: AsyncSession, user_id: UUID) -> ProviderStatus | None:
    for directory in _directories:
        found = await directory.status(session, user_id)
        if found is not None:
            return found
    return None


async def refresh(user_id: UUID, days: int = 2) -> bool:
    """Đồng bộ ngay dữ liệu gần đây (briefing chạy trước lần đồng bộ định kỳ); False khi không có nhà cung cấp."""
    refreshed = False
    for directory in _directories:
        refreshed = await directory.refresh(user_id, days) or refreshed
    return refreshed


async def user_timezone(session: AsyncSession, user_id: UUID, requested: str | None = None) -> str:
    """Múi giờ dùng để chốt "hôm nay": tham số của request, rồi múi giờ nhà cung cấp, rồi mặc định."""
    from domains.shared.schemas.tracking import DEFAULT_TIMEZONE

    if requested:
        return requested
    status = await provider_status(session, user_id)
    zone = status.timezone if status is not None else None
    try:
        ZoneInfo(zone or "")
    except (ValueError, ZoneInfoNotFoundError):
        return DEFAULT_TIMEZONE
    return zone


async def before_account_erasure(session: AsyncSession, user_id: UUID) -> None:
    for directory in _directories:
        await directory.before_account_erasure(session, user_id)


async def availability(session: AsyncSession, user_id: UUID) -> dict[str, TypeAvailability]:
    merged: dict[str, TypeAvailability] = {}
    for directory in _directories:
        merged.update(await directory.availability(session, user_id))
    return merged


async def linked_trainings(session: AsyncSession, user_id: UUID) -> set[UUID]:
    linked: set[UUID] = set()
    for directory in _directories:
        linked |= await directory.linked_trainings(session, user_id)
    return linked


async def write(session: AsyncSession, user_id: UUID, kind: str, payload: dict[str, Any] | None = None,
                point_id: UUID | None = None, delete: bool = False) -> dict[str, Any] | None:
    for directory in _directories:
        result = await directory.write(session, user_id, kind, payload, point_id, delete)
        if result is not None:
            return result
    return None
