"""Nhận ra dữ liệu chính HercFit đã ghi lên Google, để lần nhập không bao giờ tạo bản trùng.

Một data point là của chúng ta khi tên tài nguyên của nó có trong google_resource_mappings (do
HercFit sở hữu) hoặc nguồn dữ liệu của nó gọi tên OAuth client của chúng ta (`application.googleWebClientId`).
Rollup không lọc được theo cách này: chúng gộp mọi nguồn, nên tổng theo ngày có thể
bao gồm nhật ký đã xuất; vì vậy ngữ cảnh và insight báo nhật ký và tổng
của nhà cung cấp theo từng nguồn thay vì cộng chúng lại.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from core.settings import settings


async def owned_names(session, connection_id: UUID, data_type: str) -> set[str]:
    rows = await session.execute(text("""
        SELECT remote_name FROM google_resource_mappings
        WHERE connection_id = :c AND data_type = :d AND owned_by_hercfit AND remote_name IS NOT NULL"""),
        {"c": connection_id, "d": data_type})
    return {row[0] for row in rows}


def written_by_us(data_source: dict[str, Any] | None) -> bool:
    application = (data_source or {}).get("application") or {}
    client = settings.GOOGLE_OAUTH_CLIENT_ID
    return bool(client and application.get("googleWebClientId") == client)
