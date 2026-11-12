"""Nhật ký ăn uống/tập luyện thực tế; bên gọi không được truyền tổng hay cờ cũ.

Tách ra từ schemas.journals trong đợt tổ chức lại theo miền."""
from typing import Literal
from uuid import UUID

from domains.shared.schemas.common import EntityRead


class JournalRead(EntityRead):
    image_url: str | None = None
    user_id: UUID
    name: str
    timezone: str
    note: str | None
    replaces_id: UUID | None
    source: Literal["USER", "LEGACY_IMPORT"]
    detail_status: Literal["DETAILED", "AGGREGATE_ONLY"]
