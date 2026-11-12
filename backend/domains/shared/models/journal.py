"""Aggregate hoạt động thực tế bất biến với sửa nguyên tử và lệnh đọc có phạm vi.

Tách ra từ models.journals trong đợt tổ chức lại theo miền."""
from typing import Any, ClassVar
from uuid import UUID as PyUUID

from fastapi import HTTPException
from sqlalchemy import CheckConstraint, ForeignKey, String, Text, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, selectinload

from domains.shared.models.basemodel import BaseModel
from domains.shared.models.domain import lock_user, require_version
from domains.shared.schemas.tracking import JournalQuery


# Lớp cơ sở cho các nhật ký hoạt động thực tế (Training và Meal) --> Đều có tính chất ghi và kế thừa lại Object này
class Journal(BaseModel):
    __abstract__ = True
    TIME_FIELD: ClassVar[str]
    CREATE_SCHEMA: ClassVar[Any]

    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ảnh là metadata trình bày có thể thay đổi, tách khỏi dữ kiện hoạt động.
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_public_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="USER", server_default="USER", nullable=False)
    detail_status: Mapped[str] = mapped_column(String(20), default="DETAILED", server_default="DETAILED", nullable=False)

    @classmethod
    def _user_query(cls, user_id, *, include_inactive=False):
        return super()._user_query(user_id, include_inactive=include_inactive).options(selectinload(cls.items))

    @classmethod
    async def list_for_user(cls, session: AsyncSession, *, user_id: PyUUID, query: JournalQuery | None = None):
        options = JournalQuery.model_validate(query or {})
        lower, upper = options.utc_bounds()
        timestamp = getattr(cls, cls.TIME_FIELD)
        statement = cls._user_query(user_id, include_inactive=options.include_inactive)
        if lower is not None:
            statement = statement.where(timestamp >= lower)
        if upper is not None:
            statement = statement.where(timestamp < upper)
        return list((await session.scalars(statement.order_by(timestamp.desc(), cls.id.desc()).offset(options.offset).limit(options.limit))).all())

    @classmethod
    async def create_snapshot(cls, session: AsyncSession, *, user_id: PyUUID, payload):
        data = cls.CREATE_SCHEMA.model_validate(payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            return await cls._insert_snapshot(session, user_id=user_id, data=data)

    @classmethod
    async def replace_for_user(cls, session: AsyncSession, entity_id: PyUUID, *, user_id: PyUUID, payload, expected_version_id: int):
        values = payload.to_payload() if hasattr(payload, "to_payload") else dict(payload)
        async with session.begin_nested():
            await lock_user(session, user_id)
            original = (await session.execute(cls._user_query(user_id, include_inactive=True).where(cls.id == entity_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
            if original is None:
                return None
            require_version(original, expected_version_id)
            if not original.is_active:
                raise HTTPException(409, "Snapshot has been replaced or deleted")
            # Thời điểm bị bỏ trống giữ nguyên lúc hoạt động diễn ra.
            values.setdefault(cls.TIME_FIELD, getattr(original, cls.TIME_FIELD))
            data = cls.CREATE_SCHEMA.model_validate(values)
            replacement = await cls._insert_snapshot(session, user_id=user_id, data=data, replaces_id=original.id)
            # Ảnh đi theo ảnh chụp đang hoạt động, nơi cập nhật media và dọn dẹp có thể chạm tới.
            replacement.image_url, replacement.image_public_id = original.image_url, original.image_public_id
            original.image_url = original.image_public_id = None
            original.is_active = False
            await session.flush()
            return replacement

    @classmethod
    async def _check_entry(cls, session, user_id, entry_id):
        if entry_id is None:
            return
        from domains.goals_plans.models.plans import TrainingPlan, TrainingPlanEntry

        # Một lịch trong quá khứ vẫn có thể là nguồn cho một buổi tập ghi muộn.
        is_rest = await session.scalar(select(TrainingPlanEntry.is_rest).join(TrainingPlan)
                                       .where(TrainingPlanEntry.id == entry_id, TrainingPlan.user_id == user_id))
        if is_rest is None:
            raise HTTPException(404, "Scheduled activity not found")
        if is_rest:
            raise HTTPException(422, "A rest entry cannot be the source of a training")

def journal_constraints(prefix):
    return (
        CheckConstraint("name ~ '[^[:space:]]'", name=f"ck_{prefix}_name"),
        CheckConstraint("source IN ('USER', 'LEGACY_IMPORT')", name=f"ck_{prefix}_source"),
        CheckConstraint("detail_status IN ('DETAILED', 'AGGREGATE_ONLY') AND (detail_status != 'AGGREGATE_ONLY' OR source = 'LEGACY_IMPORT')", name=f"ck_{prefix}_details"),
        CheckConstraint("replaces_id IS NULL OR replaces_id <> id", name=f"ck_{prefix}_replacement"),
    )
