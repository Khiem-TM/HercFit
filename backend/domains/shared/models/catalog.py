"""Hành vi dùng chung cho danh mục hệ thống/tuỳ chỉnh (thực phẩm và bài tập)."""

import unicodedata
from typing import Any, ClassVar
from uuid import UUID as PyUUID

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.catalog_lock import catalog_write
from domains.shared.models.domain import require_version
from domains.shared.schemas.common import UserScope
from domains.shared.schemas.enums import FoodSourceType

# Cửa sổ ứng viên cho tìm kiếm có xếp hạng; việc xếp hạng làm trong Python (phân biệt dấu).
SEARCH_CANDIDATES = 300


def normalize_food_text(value: str) -> str:
    value = unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
    return " ".join(
        "".join(char for char in value if not unicodedata.combining(char)).split()
    )


def apply_search_text(entity: Any, *parts: str | None) -> None:
    """Duy trì các cột tìm kiếm suy ra khi ORM ghi, kể cả CRUD kế thừa từ BaseModel."""
    entity.normalized_name_vi = normalize_food_text(entity.name_vi or "")
    entity.normalized_name_en = normalize_food_text(entity.name_en) if entity.name_en else None
    entity.normalized_search_text = normalize_food_text(" ".join(part for part in parts if part))


class CatalogMixin:
    """Dòng SYSTEM hiển thị với mọi người; dòng CUSTOM chỉ với chủ sở hữu.

    Kết hợp với BaseModel; model cung cấp source_type, owner_user_id và ALIAS_TABLE.
    """

    ALIAS_TABLE: ClassVar[Any]

    @classmethod
    def _custom_scope(cls, user_id: PyUUID) -> Any:
        user_id = UserScope(user_id=user_id).user_id
        return and_(cls.source_type == FoodSourceType.CUSTOM, cls.owner_user_id == user_id)

    @classmethod
    def _visible_query(cls, user_id: PyUUID, *, include_inactive: bool = False) -> Select:
        query = select(cls).where(or_(
            cls.source_type == FoodSourceType.SYSTEM,
            cls._custom_scope(user_id),
        ))
        return cls.apply_active_scope(query, include_inactive=include_inactive)

    @classmethod
    def _text_match(cls, normalized: str) -> Any:
        """Nguyên cụm từ, mọi token, hoặc một bí danh, so với văn bản tìm kiếm không dấu."""
        return or_(
            cls.normalized_search_text.contains(normalized, autoescape=True),
            and_(*[cls.normalized_search_text.contains(token, autoescape=True) for token in normalized.split()]),
            exists().where(cls.ALIAS_TABLE.c.entity_id == cls.id,
                           cls.ALIAS_TABLE.c.normalized_alias.contains(normalized, autoescape=True)),
        )

    @classmethod
    async def get_visible_by_id(
        cls, session: AsyncSession, entity_id: PyUUID, *, user_id: PyUUID,
        include_inactive: bool = False,
    ):
        result = await session.execute(
            cls._visible_query(user_id, include_inactive=include_inactive).where(cls.id == entity_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def _get_custom_for_update(
        cls, session: AsyncSession, entity_id: PyUUID, *, user_id: PyUUID,
        include_inactive: bool = False,
    ):
        query = cls.apply_active_scope(
            select(cls).where(cls.id == entity_id, cls._custom_scope(user_id)),
            include_inactive=include_inactive,
        )
        result = await session.execute(query.with_for_update().execution_options(populate_existing=True))
        return result.scalar_one_or_none()

    @classmethod
    @catalog_write
    async def _set_custom_active(
        cls, session: AsyncSession, entity_id: PyUUID, *, user_id: PyUUID, active: bool,
        expected_version_id: int | None = None,
    ):
        async with session.begin_nested():
            entity = await cls._get_custom_for_update(
                session, entity_id, user_id=user_id, include_inactive=True,
            )
            if entity is None:
                return None
            if expected_version_id is not None:
                require_version(entity, expected_version_id)
            await cls._set_active(session, entity, active)
        return entity

    @classmethod
    async def soft_delete_custom(
        cls, session: AsyncSession, entity_id: PyUUID, *, user_id: PyUUID,
        expected_version_id: int | None = None,
    ):
        return await cls._set_custom_active(
            session, entity_id, user_id=user_id, active=False, expected_version_id=expected_version_id,
        )

    @classmethod
    async def restore_custom(
        cls, session: AsyncSession, entity_id: PyUUID, *, user_id: PyUUID,
        expected_version_id: int | None = None,
    ):
        return await cls._set_custom_active(
            session, entity_id, user_id=user_id, active=True, expected_version_id=expected_version_id,
        )
