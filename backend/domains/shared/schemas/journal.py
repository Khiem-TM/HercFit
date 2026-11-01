"""Actual food/training logs; callers cannot supply totals or legacy flags.

Split from schemas.journals in the domain reorganization."""
from datetime import timezone
from typing import Literal
from uuid import UUID
from domains.shared.schemas.common import EntityRead


class JournalRead(EntityRead):
    image_url: str | None = None
    user_id: UUID
    name: str
    timezone: str
    note: str | None
    source_entry_id: UUID | None
    replaces_id: UUID | None
    source: Literal["USER", "LEGACY_IMPORT"]
    detail_status: Literal["DETAILED", "AGGREGATE_ONLY"]
