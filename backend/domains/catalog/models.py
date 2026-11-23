"""Model ORM của miền catalog thực phẩm và bài tập."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    Select,
    String,
    Text,
    column,
    event,
    func,
    inspect,
    or_,
    select,
    table,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from core.catalog_lock import catalog_write
from domains.catalog.schemas import (
    ExerciseConfiguration,
    ExerciseCreate,
    ExerciseKind,
    ExerciseQuery,
    ExerciseUpdateRequest,
    FoodCreate,
    FoodQuery,
    FoodUpdate,
    MuscleGroup,
    muscle_name,
)
from domains.shared.models import (
    SEARCH_CANDIDATES,
    BaseModel,
    CatalogMixin,
    apply_search_text,
    normalize_food_text,
    require_version,
    try_lock_user,
    uuid7,
)
from domains.shared.schemas import FoodItemType, FoodServingUnit, FoodSourceType, UserScope

# --------------------------------------------------------------------------------------------------
# Danh mục bài tập hệ thống/tuỳ chỉnh với lệnh ghi có phạm vi và phiên bản lạc quan.
# --------------------------------------------------------------------------------------------------

if TYPE_CHECKING:
    from domains.identity.models import User

_EXERCISE_ALIASES = table("exercises_aliases", column("entity_id"), column("normalized_alias"))

_configuration_adapter = TypeAdapter(ExerciseConfiguration)


class Exercise(CatalogMixin, BaseModel):
    __tablename__ = "exercises"
    __table_args__ = (
        CheckConstraint(
            "(source_type = 'SYSTEM' AND owner_user_id IS NULL) OR "
            "(source_type = 'CUSTOM' AND owner_user_id IS NOT NULL)",
            name="ck_exercises_owner",
        ),
        CheckConstraint("code ~ '[^[:space:]]'", name="ck_exercises_code"),
        CheckConstraint("name_vi ~ '[^[:space:]]'", name="ck_exercises_name"),
        CheckConstraint("jsonb_typeof(equipment) = 'array'", name="ck_exercises_equipment_array"),
        CheckConstraint("jsonb_typeof(muscle_groups) = 'array'", name="ck_exercises_muscle_groups_array"),
        CheckConstraint(
            "jsonb_typeof(configuration) = 'object' AND configuration ? 'kind' "
            "AND configuration->>'kind' = kind::text", name="ck_exercises_configuration_kind",
        ),
        Index("uq_exercises_system_code", "kind", "code", unique=True,
              postgresql_where=text("source_type = 'SYSTEM'")),
        Index("ix_exercises_browse", "normalized_name_vi", "id"),
    )

    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name_vi: Mapped[str] = mapped_column(String(512), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(512), nullable=True)
    kind: Mapped[ExerciseKind] = mapped_column(
        Enum(ExerciseKind, name="exercise_kind", validate_strings=True), nullable=False,
    )
    source_type: Mapped[FoodSourceType] = mapped_column(
        Enum(FoodSourceType, name="food_source_type", validate_strings=True),
        default=FoodSourceType.SYSTEM, server_default="SYSTEM", nullable=False,
    )
    owner_user_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True,
    )
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    equipment: Mapped[list[str]] = mapped_column(
        JSONB(none_as_null=True), default=list, server_default=text("'[]'::jsonb"), nullable=False,
    )
    muscle_groups: Mapped[list[str]] = mapped_column(
        JSONB(none_as_null=True), default=list, server_default=text("'[]'::jsonb"), nullable=False,
    )
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB(none_as_null=True), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_public_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_search_text: Mapped[str] = mapped_column(Text, nullable=False)

    ALIAS_TABLE = _EXERCISE_ALIASES

    owner: Mapped[User | None] = relationship("User")

    @classmethod
    def _visible_query(cls, user_id: PyUUID, *, include_inactive: bool = False) -> Select:
        from domains.identity.models import User

        user_id = UserScope(user_id=user_id).user_id
        return super()._visible_query(user_id, include_inactive=include_inactive).where(
            select(User.id).where(User.id == user_id, User.is_active.is_(True)).exists(),
        )

    @classmethod
    async def list_visible(
        cls, session: AsyncSession, *, user_id: PyUUID, search: str | None = None,
        source_type: FoodSourceType | None = None, kind: ExerciseKind | None = None,
        offset: int = 0, limit: int = 50, include_inactive: bool = False,
    ) -> list[Exercise]:
        options = ExerciseQuery(
            search=search, source_type=source_type, kind=kind,
            offset=offset, limit=limit, include_inactive=include_inactive,
        )
        query = cls._visible_query(user_id, include_inactive=options.include_inactive)
        if options.source_type is not None:
            query = query.where(cls.source_type == options.source_type)
        if options.kind is not None:
            query = query.where(cls.kind == options.kind)
        normalized = normalize_food_text(options.search) if options.search else ""
        if not normalized:
            result = await session.execute(
                query.order_by(cls.normalized_name_vi, cls.id).offset(options.offset).limit(options.limit)
            )
            return list(result.scalars().all())
        from domains.catalog.services import rank

        similarity = func.similarity(cls.normalized_search_text, normalized)
        window = max(SEARCH_CANDIDATES, options.offset + options.limit)
        rows = (await session.execute(
            query.where(cls._text_match(normalized)).order_by(similarity.desc(), cls.id).limit(window)
        )).scalars().all()
        ranked = rank(
            options.search, rows, name=lambda exercise: exercise.name_vi,
            others=lambda exercise: (exercise.name_en or "", exercise.code or ""),
            owned=lambda exercise: exercise.source_type == FoodSourceType.CUSTOM,
        )
        return ranked[options.offset: options.offset + options.limit]

    @classmethod
    @catalog_write
    async def create_custom(
        cls, session: AsyncSession, *, user_id: PyUUID,
        payload: ExerciseCreate | Mapping[str, Any],
    ) -> Exercise:
        user_id = UserScope(user_id=user_id).user_id
        values = ExerciseCreate.model_validate(payload).model_dump(mode="json")
        values["code"] = values["code"] or str(uuid7())
        async with session.begin_nested():
            if await try_lock_user(session, user_id) is None:
                raise HTTPException(status_code=404, detail="User not found")
            exercise = await cls.create(session, {
                **values, "source_type": FoodSourceType.CUSTOM, "owner_user_id": user_id,
            })
        return exercise

    @classmethod
    async def get_system_by_code(
        cls, session: AsyncSession, code: str, *, kind: ExerciseKind,
        include_inactive: bool = False,
    ) -> Exercise | None:
        return await cls.get_one(
            session, code=code, kind=ExerciseKind(kind), source_type=FoodSourceType.SYSTEM,
            include_inactive=include_inactive,
        )

    @classmethod
    async def _get_custom_for_update(
        cls, session: AsyncSession, exercise_id: PyUUID, *, user_id: PyUUID,
        include_inactive: bool = False,
    ) -> Exercise | None:
        if await try_lock_user(session, user_id) is None:
            return None
        return await super()._get_custom_for_update(
            session, exercise_id, user_id=user_id, include_inactive=include_inactive,
        )

    @classmethod
    @catalog_write
    async def update_custom(
        cls, session: AsyncSession, exercise_id: PyUUID, *, user_id: PyUUID,
        payload: ExerciseUpdateRequest | Mapping[str, Any],
    ) -> Exercise | None:
        request = ExerciseUpdateRequest.model_validate(payload)
        values = request.model_dump(mode="json", exclude_unset=True, exclude={"expected_version_id"})
        async with session.begin_nested():
            exercise = await cls._get_custom_for_update(session, exercise_id, user_id=user_id)
            if exercise is None:
                return None
            require_version(exercise, request.expected_version_id)
            if "configuration" in values and values["configuration"]["kind"] != exercise.kind:
                raise HTTPException(422, "configuration.kind must match exercise kind")
            for key, value in values.items():
                setattr(exercise, key, value)
            await session.flush()
            await session.refresh(exercise)
        return exercise


@event.listens_for(Exercise, "before_insert")
@event.listens_for(Exercise, "before_update")
def _validate_exercise(_mapper: Mapper, _connection: Connection, exercise: Exercise) -> None:
    state = inspect(exercise)
    if state.persistent and any(
        state.attrs[field].history.has_changes() for field in ("owner_user_id", "source_type", "kind")
    ):
        raise ValueError("Exercise owner, source and kind cannot be changed")
    configuration = _configuration_adapter.validate_python(exercise.configuration)
    if configuration.kind != exercise.kind:
        raise ValueError("configuration.kind must match exercise kind")
    exercise.configuration = configuration.model_dump(mode="json")
    if exercise.kind == ExerciseKind.STRENGTH:
        # Phân tích sức mạnh gom nhóm theo bộ từ vựng này; từ chối tên cơ tự do.
        exercise.muscle_groups = [MuscleGroup(muscle_name(group)).value for group in exercise.muscle_groups or []]
    apply_search_text(
        exercise, exercise.code, exercise.name_vi, exercise.name_en, exercise.instructions,
        *(exercise.equipment or []), *(exercise.muscle_groups or []),
    )


# --------------------------------------------------------------------------------------------------
# foods
# --------------------------------------------------------------------------------------------------

# Xếp hạng theo mật độ protein bỏ qua gia vị và chất béo: nước mắm giàu protein nhưng không phải bữa ăn.
NON_MEAL_CATEGORIES = ("Gia vị, nước chấm", "Dầu, mỡ, bơ")
MIN_DENSITY_ENERGY_KCAL = 20
# catalog_search.score: 25 đòi mọi từ của truy vấn có trong tên (không dấu) cùng với cùng từ đầu.
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
    # Đơn vị đo gia dụng ([{label, quantity, unit, source}]) theo đúng serving_unit của món,
    # ví dụ "1 tô" = 500 G: quy lượng người dùng nói theo tô/suất ra gam/ml.
    portions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(none_as_null=True), default=list, server_default=text("'[]'::jsonb"), nullable=False,
    )
    normalized_name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_search_text: Mapped[str] = mapped_column(Text, nullable=False)

    ALIAS_TABLE = _FOOD_ALIASES

    owner: Mapped[User | None] = relationship("User", back_populates="custom_foods")

    @classmethod
    def _protein_density_scope(cls, query: Select) -> Select:
        """Các bản ghi có thể xếp hạng theo protein trên kcal mà không gây hiểu lầm."""
        macro_energy = 4 * cls.protein_g + 4 * cls.carbohydrate_g + 9 * cls.fat_g
        return query.where(
            cls.energy_kcal >= MIN_DENSITY_ENERGY_KCAL,
            cls.protein_g > 0,
            # Riêng protein không thể mang nhiều năng lượng hơn cả thực phẩm (lỗi nhập liệu).
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
            return await cls._with_aliases(session, await cls._ranked(
                session, query, options.search, options.sort, options.offset, options.limit))
        # Nhiều tên trong một lần gọi (gợi ý bữa ăn): kết quả khớp tốt nhất của từng tên, theo thứ tự yêu cầu.
        per_name = max(1, options.limit // len(options.names))
        seen, results = set(), []
        for name in options.names:
            for food in await cls._ranked(session, query, name, options.sort, 0, per_name):
                if food.id not in seen:
                    seen.add(food.id)
                    results.append(food)
        return await cls._with_aliases(session, results)

    @classmethod
    async def _with_aliases(cls, session: AsyncSession, foods: list[FoodItem]) -> list[FoodItem]:
        """Gắn alias (dạng chuẩn hoá) vào kết quả để bên gọi khớp được "chả giò" với "Nem rán"; một truy vấn cho cả lô."""
        if foods:
            rows = await session.execute(select(_FOOD_ALIASES.c.entity_id, _FOOD_ALIASES.c.normalized_alias)
                                         .where(_FOOD_ALIASES.c.entity_id.in_([food.id for food in foods])))
            aliases: dict[PyUUID, list[str]] = {}
            for entity_id, alias in rows:
                aliases.setdefault(entity_id, []).append(alias)
            for food in foods:
                food.aliases = sorted(aliases.get(food.id, []))
        return foods

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
        from domains.catalog.services import score

        similarity = func.similarity(cls.normalized_search_text, normalized_search)
        window = max(SEARCH_CANDIDATES, offset + limit)
        rows = (await session.execute(query.order_by(similarity.desc(), cls.id).limit(window))).scalars().all()
        scored = sorted(((score(search, food.name_vi or "", (food.name_en or "", food.category_vi or ""),
                                owned=food.source_type == FoodSourceType.CUSTOM), index, food)
                         for index, food in enumerate(rows)), key=lambda row: (-row[0], row[1]))
        if sort != "protein_density":
            return [food for _score, _index, food in scored][offset: offset + limit]
        # Kết quả liên quan đứng trước (ít nhất khớp nguyên từ), rồi trong số đó lấy nhiều protein trên kcal nhất.
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
