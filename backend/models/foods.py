from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    CheckConstraint, Enum, ForeignKey, Index, Numeric, Select, String, Text,
    and_, event, or_, select, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from models.basemodel import BaseModel, uuid7

if TYPE_CHECKING:
    from models.user import User

# Thực phẩm được chia ra thành 2 nguồn dữ liệu 
## Nguồn dữ liệu hệ thống (SYSTEM): là những thực phẩm được cung cấp sẵn bởi hệ thống, không thể chỉnh sửa bởi người dùng.
## Nguồn dữ liệu người dùng (CUSTOM): là những thực phẩm do người dùng tạo hoặc yêu cầu ghi nhận nằm ngoài data dữ liệu --> Agent thực thị web search và bổ sung dựa trên yêu cầu và chấp thuân từ người dùng

class FoodSourceType(StrEnum):
    SYSTEM = "SYSTEM"
    CUSTOM = "CUSTOM"

# Thực phẩm được chia ra thành 2 loại chính
## Loại thực phẩm (FOOD): là những thực phẩm đơn lẻ hoặc sản phẩm đóng hộp
## Loại món ăn (DISH): là những món ăn được chế biến từ nhiều thực phẩm khác nhau, có thể có công thức chế biến và thành phần dinh dưỡng khác nhau
class FoodItemType(StrEnum):
    FOOD = "FOOD"
    DISH = "DISH"

# đơn vị đo lường 
class FoodServingUnit(StrEnum):
    G = "G"
    ML = "ML"


def normalize_food_text(value: str) -> str:
    value = unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
    return " ".join(
        "".join(char for char in value if not unicodedata.combining(char)).split()
    )


class FoodItem(BaseModel):
    __tablename__ = "foods"
    __table_args__ = (
        CheckConstraint(
            "(source_type = 'SYSTEM' AND owner_user_id IS NULL) OR "
            "(source_type = 'CUSTOM' AND owner_user_id IS NOT NULL)",
            name="ck_foods_owner",
        ),
        CheckConstraint("name_vi ~ '[^[:space:]]'", name="ck_foods_name"),
        CheckConstraint("code ~ '[^[:space:]]'", name="ck_foods_code"),
        CheckConstraint(
            "serving_size > 0 AND serving_size < 100000000",
            name="ck_foods_serving",
        ),
        *[
            CheckConstraint(
                f"{field} >= 0 AND {field} < 1000000000000",
                name=f"ck_foods_{field}",
            )
            for field in ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g")
        ],
        Index(
            "uq_foods_system_code", "item_type", "code", unique=True,
            postgresql_where=text("source_type = 'SYSTEM'"),
        ),
        Index("ix_foods_browse", "normalized_name_vi", "id"),
    )

    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name_vi: Mapped[str] = mapped_column(String(512), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(512), nullable=True)
    category_vi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_type: Mapped[FoodItemType] = mapped_column(
        Enum(FoodItemType, name="food_item_type", validate_strings=True),
        default=FoodItemType.FOOD, server_default="FOOD", nullable=False,
    )
    source_type: Mapped[FoodSourceType] = mapped_column(
        Enum(FoodSourceType, name="food_source_type", validate_strings=True),
        default=FoodSourceType.SYSTEM, server_default="SYSTEM", nullable=False,
    )
    # ID của người dùng sở hữu thực phẩm (nếu là thực phẩm tùy chỉnh)
    owner_user_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=True,
    )
    serving_size: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    serving_unit: Mapped[FoodServingUnit] = mapped_column(
        Enum(FoodServingUnit, name="food_serving_unit", validate_strings=True),
        default=FoodServingUnit.G, server_default="G", nullable=False,
    )
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    carbohydrate_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    nutrition_information: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), default=dict,
        server_default=text("'{}'::jsonb"), nullable=False,
    )
    data_quality: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True,
    )
    normalized_name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_search_text: Mapped[str] = mapped_column(Text, nullable=False)

    owner: Mapped[User | None] = relationship("User", back_populates="custom_foods")

    @classmethod
    def _food_payload(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        allowed_fields = {
            "code", "name_vi", "name_en", "category_vi", "category_en", "item_type",
            "serving_size", "serving_unit", "energy_kcal", "protein_g",
            "carbohydrate_g", "fat_g", "fiber_g", "nutrition_information", "data_quality",
        }
        return {key: value for key, value in payload.items() if key in allowed_fields}

    @classmethod
    def _custom_scope(cls, user_id: PyUUID) -> Any:
        if user_id is None:
            raise ValueError("user_id is required")
        return and_(
            cls.source_type == FoodSourceType.CUSTOM,
            cls.owner_user_id == user_id,
        )

    @classmethod
    def _visible_query(cls, user_id: PyUUID, *, include_inactive: bool = False) -> Select:
        query = select(cls).where(or_(
            cls.source_type == FoodSourceType.SYSTEM,
            cls._custom_scope(user_id),
        ))
        return cls.apply_active_scope(query, include_inactive=include_inactive)

    @classmethod
    async def get_visible_by_id(
        cls, session: AsyncSession, food_id: PyUUID, *, user_id: PyUUID,
        include_inactive: bool = False,
    ) -> FoodItem | None:
        query = cls._visible_query(user_id, include_inactive=include_inactive)
        result = await session.execute(query.where(cls.id == food_id))
        return result.scalar_one_or_none()

    @classmethod
    async def list_visible(
        cls, session: AsyncSession, *, user_id: PyUUID, search: str | None = None,
        source_type: FoodSourceType | None = None, item_type: FoodItemType | None = None,
        offset: int = 0, limit: int = 50, include_inactive: bool = False,
    ) -> list[FoodItem]:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("limit must be between 1 and 200; offset must be non-negative")
        query = cls._visible_query(user_id, include_inactive=include_inactive)
        if search and (normalized_search := normalize_food_text(search)):
            query = query.where(
                cls.normalized_search_text.contains(normalized_search, autoescape=True)
            )
        if source_type is not None:
            query = query.where(cls.source_type == FoodSourceType(source_type))
        if item_type is not None:
            query = query.where(cls.item_type == FoodItemType(item_type))
        query = query.order_by(cls.normalized_name_vi, cls.id).offset(offset).limit(limit)
        result = await session.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def create_custom(
        cls, session: AsyncSession, *, user_id: PyUUID, payload: Mapping[str, Any],
    ) -> FoodItem:
        if user_id is None:
            raise ValueError("user_id is required")
        values = cls._food_payload(payload)
        if values.get("code") is None:
            values["code"] = str(uuid7())
        values.update(source_type=FoodSourceType.CUSTOM, owner_user_id=user_id)
        return await cls.create(session, values)

    @classmethod
    async def create_system(
        cls, session: AsyncSession, *, payload: Mapping[str, Any],
    ) -> FoodItem:
        values = cls._food_payload(payload)
        values.update(source_type=FoodSourceType.SYSTEM, owner_user_id=None)
        return await cls.create(session, values)

    @classmethod
    async def get_system_by_code(
        cls, session: AsyncSession, code: str, *, item_type: FoodItemType = FoodItemType.FOOD,
        include_inactive: bool = False,
    ) -> FoodItem | None:
        return await cls.get_one(
            session, code=code, item_type=FoodItemType(item_type),
            source_type=FoodSourceType.SYSTEM, include_inactive=include_inactive,
        )

    @classmethod
    async def _get_custom_for_update(
        cls, session: AsyncSession, food_id: PyUUID, *, user_id: PyUUID,
        include_inactive: bool = False,
    ) -> FoodItem | None:
        query = select(cls).where(cls.id == food_id, cls._custom_scope(user_id))
        query = cls.apply_active_scope(query, include_inactive=include_inactive)
        result = await session.execute(query.with_for_update())
        return result.scalar_one_or_none()

    @classmethod
    async def update_custom(
        cls, session: AsyncSession, food_id: PyUUID, *, user_id: PyUUID,
        payload: Mapping[str, Any],
    ) -> FoodItem | None:
        food = await cls._get_custom_for_update(session, food_id, user_id=user_id)
        if food is None:
            return None
        for key, value in cls._food_payload(payload).items():
            setattr(food, key, value)
        await session.flush()
        await session.refresh(food)
        return food

    @classmethod
    async def _set_custom_active(
        cls, session: AsyncSession, food_id: PyUUID, *, user_id: PyUUID, active: bool,
    ) -> FoodItem | None:
        food = await cls._get_custom_for_update(
            session, food_id, user_id=user_id, include_inactive=True,
        )
        if food is not None and food.is_active != active:
            food.is_active = active
            await session.flush()
            await session.refresh(food)
        return food

    @classmethod
    async def soft_delete_custom(
        cls, session: AsyncSession, food_id: PyUUID, *, user_id: PyUUID,
    ) -> FoodItem | None:
        return await cls._set_custom_active(session, food_id, user_id=user_id, active=False)

    @classmethod
    async def restore_custom(
        cls, session: AsyncSession, food_id: PyUUID, *, user_id: PyUUID,
    ) -> FoodItem | None:
        return await cls._set_custom_active(session, food_id, user_id=user_id, active=True)


@event.listens_for(FoodItem, "before_insert")
@event.listens_for(FoodItem, "before_update")
def _normalize_food_search(_mapper: Mapper, _connection: Connection, food: FoodItem) -> None:
    """Maintain derived text for ORM writes, including inherited BaseModel CRUD."""
    food.normalized_name_vi = normalize_food_text(food.name_vi or "")
    food.normalized_name_en = (
        normalize_food_text(food.name_en) if food.name_en is not None else None
    )
    food.normalized_search_text = normalize_food_text(" ".join(
        value for value in (
            food.code, food.name_vi, food.name_en, food.category_vi, food.category_en,
        ) if value
    ))
