from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    CheckConstraint, Enum, ForeignKey, Index, Numeric, Select, String, Text,
    column, event, func, or_, table, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from models.basemodel import BaseModel, uuid7
from models.catalog import SEARCH_CANDIDATES, CatalogMixin, apply_search_text, normalize_food_text
from core.catalog_lock import catalog_write
from models.domain import require_version
from schemas.common import UserScope
from schemas.enums import FoodItemType, FoodServingUnit, FoodSourceType
from schemas.foods import FoodCreate, FoodQuery, FoodUpdate, SystemFoodCreate

if TYPE_CHECKING:
    from models.user import User

# Ranking by protein density skips seasonings and fats: fish sauce is protein-dense but not a meal.
NON_MEAL_CATEGORIES = ("Gia vị, nước chấm", "Dầu, mỡ, bơ")
MIN_DENSITY_ENERGY_KCAL = 20
# catalog_search.score: 25 needs every query word in the name (unaccented) plus the same head word.
MIN_DENSITY_RELEVANCE = 25
_FOOD_ALIASES = table("foods_aliases", column("entity_id"), column("normalized_alias"))


class FoodItem(CatalogMixin, BaseModel):
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
        CheckConstraint("jsonb_typeof(portions) = 'array'", name="ck_foods_portions"),
        CheckConstraint(
            "portion_weight_g IS NULL OR (portion_weight_g > 0 AND portion_weight_g < 100000)",
            name="ck_foods_portion_weight",
        ),
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
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_public_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Household measures ([{label, quantity, unit, source}]) and, for PORTION
    # foods, the gram weight of one serving when the source publishes it.
    portions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), default=list, server_default=text("'[]'::jsonb"), nullable=False,
    )
    portion_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    normalized_name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_search_text: Mapped[str] = mapped_column(Text, nullable=False)

    ALIAS_TABLE = _FOOD_ALIASES

    owner: Mapped[User | None] = relationship("User", back_populates="custom_foods")

    @classmethod
    def _protein_density_scope(cls, query: Select) -> Select:
        """Records that can be ranked by protein per kcal without misleading anyone."""
        macro_energy = 4 * cls.protein_g + 4 * cls.carbohydrate_g + 9 * cls.fat_g
        return query.where(
            cls.energy_kcal >= MIN_DENSITY_ENERGY_KCAL,
            cls.protein_g > 0,
            # Protein alone cannot carry more energy than the whole food (data-entry errors).
            4 * cls.protein_g <= cls.energy_kcal * 1.2,
            or_(cls.carbohydrate_g.is_(None), cls.fat_g.is_(None),
                func.abs(macro_energy - cls.energy_kcal) <= cls.energy_kcal * 0.5),
            or_(cls.category_vi.is_(None), cls.category_vi.notin_(NON_MEAL_CATEGORIES)),
        )

    @classmethod
    async def list_visible(
        cls, session: AsyncSession, *, user_id: PyUUID, search: str | None = None,
        source_type: FoodSourceType | None = None, item_type: FoodItemType | None = None,
        offset: int = 0, limit: int = 50, include_inactive: bool = False, sort: str = "relevance",
        names: list[str] | None = None,
    ) -> list[FoodItem]:
        options = FoodQuery(
            search=search, source_type=source_type, item_type=item_type, offset=offset, limit=limit,
            include_inactive=include_inactive, sort=sort, names=names,
        )
        query = cls._visible_query(user_id, include_inactive=options.include_inactive)
        if options.source_type is not None:
            query = query.where(cls.source_type == options.source_type)
        if options.item_type is not None:
            query = query.where(cls.item_type == options.item_type)
        if not options.names:
            return await cls._ranked(session, query, options.search, options.sort, options.offset, options.limit)
        # Several names in one call (meal suggestions): the best matches of each, in request order.
        per_name = max(1, options.limit // len(options.names))
        seen, results = set(), []
        for name in options.names:
            for food in await cls._ranked(session, query, name, options.sort, 0, per_name):
                if food.id not in seen:
                    seen.add(food.id)
                    results.append(food)
        return results

    @classmethod
    async def _ranked(cls, session: AsyncSession, query: Select, search: str | None, sort: str,
                      offset: int, limit: int) -> list[FoodItem]:
        normalized_search = normalize_food_text(search) if search else ""
        if normalized_search:
            query = query.where(cls._text_match(normalized_search))
        if sort == "protein_density":
            query = cls._protein_density_scope(query)
            if not normalized_search:
                density = cls.protein_g / cls.energy_kcal
                query = query.order_by(density.desc(), cls.normalized_name_vi, cls.id).offset(offset).limit(limit)
                return list((await session.execute(query)).scalars().all())
        elif not normalized_search:
            query = query.order_by(cls.normalized_name_vi, cls.id).offset(offset).limit(limit)
            return list((await session.execute(query)).scalars().all())
        from services.catalog_search import score

        similarity = func.similarity(cls.normalized_search_text, normalized_search)
        window = max(SEARCH_CANDIDATES, offset + limit)
        rows = (await session.execute(query.order_by(similarity.desc(), cls.id).limit(window))).scalars().all()
        scored = sorted(((score(search, food.name_vi or "", (food.name_en or "", food.category_vi or ""),
                                owned=food.source_type == FoodSourceType.CUSTOM), index, food)
                         for index, food in enumerate(rows)), key=lambda row: (-row[0], row[1]))
        if sort != "protein_density":
            return [food for _score, _index, food in scored][offset: offset + limit]
        # Relevant matches first (a whole-word match at least), then the most protein per kcal among them.
        pool = [food for value, _index, food in scored if value >= MIN_DENSITY_RELEVANCE][:max(3 * limit, 10)]
        pool.sort(key=lambda food: float(food.protein_g) / float(food.energy_kcal), reverse=True)
        return pool[offset: offset + limit]

    @classmethod
    @catalog_write
    async def create_custom(
        cls, session: AsyncSession, *, user_id: PyUUID, payload: Mapping[str, Any],
    ) -> FoodItem:
        user_id = UserScope(user_id=user_id).user_id
        values = FoodCreate.model_validate(payload).to_payload()
        if values.get("code") is None:
            values["code"] = str(uuid7())
        values.update(source_type=FoodSourceType.CUSTOM, owner_user_id=user_id)
        return await cls.create(session, values)

    @classmethod
    @catalog_write
    async def create_system(
        cls, session: AsyncSession, *, payload: Mapping[str, Any],
    ) -> FoodItem:
        values = SystemFoodCreate.model_validate(payload).to_payload()
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
    @catalog_write
    async def update_custom(
        cls, session: AsyncSession, food_id: PyUUID, *, user_id: PyUUID,
        payload: Mapping[str, Any],
        expected_version_id: int | None = None,
    ) -> FoodItem | None:
        values = FoodUpdate.model_validate(payload).to_payload()
        food = await cls._get_custom_for_update(session, food_id, user_id=user_id)
        if food is None:
            return None
        if expected_version_id is not None:
            require_version(food, expected_version_id)
        for key, value in values.items():
            setattr(food, key, value)
        await session.flush()
        await session.refresh(food)
        return food


@event.listens_for(FoodItem, "before_insert")
@event.listens_for(FoodItem, "before_update")
def _normalize_food_search(_mapper: Mapper, _connection: Connection, food: FoodItem) -> None:
    apply_search_text(food, food.code, food.name_vi, food.name_en, food.category_vi, food.category_en)
