"""Model ORM của miền dùng chung."""

import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar, Self
from uuid import UUID as PyUUID

from fastapi import HTTPException, status
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Select,
    String,
    Text,
    and_,
    asc,
    desc,
    event,
    exists,
    func,
    inspect,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, selectinload

from core.catalog_lock import catalog_write
from core.database import Base
from domains.catalog.schemas import (
    NUTRIENT_FIELDS,
    ExerciseActivityInput,
    ExerciseKind,
    ExercisePrescriptionInput,
    ExerciseRead,
    FoodPortionInput,
    FoodRead,
    NutritionTotals,
)
from domains.shared.schemas import (
    FoodSourceType,
    JournalQuery,
    OrderBy,
    Pagination,
    UserScope,
    VersionCheck,
)
from domains.training.metrics import estimate_kcal, item_metrics

# --------------------------------------------------------------------------------------------------
# Hàm dựng ảnh chụp catalog dùng chung cho mục kế hoạch (chỉ định) và mục thực tế (thành tích).
# --------------------------------------------------------------------------------------------------

# Cột dinh dưỡng vĩ mô --> Được sử dụng tại FoodPortionMixin và Meal (nhật ký bữa ăn)
class NutrientColumns:
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    carbohydrate_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


# Cấu trúc khẩu phần món ăn
class FoodPortionMixin(NutrientColumns):
    position: Mapped[int] = mapped_column(Integer, nullable=False) # thứ tự của món ăn trong bữa ăn
    food_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("foods.id", ondelete="SET NULL"), nullable=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)
    food_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    nutrition_information: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    nutrition_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


# Tham chiếu bài tập chung cho lịch tập và nhật ký thực tế
class ExerciseRefMixin:
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    exercise_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="SET NULL"), nullable=True,
    )
    exercise_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


# Kết quả thực tế: chi tiết theo môn nằm trong JSONB, chỉ số tổng hợp do server tính
# và lưu thành cột để analytics chỉ cần SUM/MAX thay vì đọc JSONB.
class ExerciseActualMixin(ExerciseRefMixin):
    performance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    calorie_estimate: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    energy_kcal: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kind: Mapped[ExerciseKind | None] = mapped_column(Enum(ExerciseKind, name="exercise_kind", validate_strings=True, create_type=False), nullable=True)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    distance_meters: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    elevation_gain_meters: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    volume_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    best_e1rm_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    hard_sets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    working_sets: Mapped[int | None] = mapped_column(Integer, nullable=True)


# Chỉ định trong lịch tập: khoảng reps, %1RM, bước interval... không phải kết quả.
class ExercisePlanMixin(ExerciseRefMixin):
    prescription: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


ITEM_METRIC_FIELDS = ("duration_seconds", "distance_meters", "elevation_gain_meters", "volume_kg", "best_e1rm_kg", "hard_sets", "working_sets")


def nutrient_constraints(prefix: str):
    return tuple(CheckConstraint(f"{field} IS NULL OR ({field} >= 0 AND {field} < 1000000000000)", name=f"ck_{prefix}_{field}") for field in NUTRIENT_FIELDS)


def food_item_constraints(prefix: str):
    return (
        *nutrient_constraints(prefix),
        CheckConstraint("position >= 0", name=f"ck_{prefix}_position"),
        CheckConstraint("quantity > 0 AND quantity < 100000000", name=f"ck_{prefix}_quantity"),
        CheckConstraint("unit IN ('G', 'ML')", name=f"ck_{prefix}_unit"),
        CheckConstraint("jsonb_typeof(food_snapshot) = 'object'", name=f"ck_{prefix}_snapshot"),
        CheckConstraint("jsonb_typeof(nutrition_information) = 'object'", name=f"ck_{prefix}_nutrition"),
    )


def exercise_item_constraints(prefix: str):
    return (
        CheckConstraint("position >= 0", name=f"ck_{prefix}_position"),
        CheckConstraint("energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal < 1000000000000)", name=f"ck_{prefix}_energy"),
        *(CheckConstraint(f"jsonb_typeof({field}) = 'object'", name=f"ck_{prefix}_{field}")
          for field in ("exercise_snapshot", "performance", "calorie_estimate")),
        *(CheckConstraint(f"{field} IS NULL OR {field} >= 0", name=f"ck_{prefix}_{field}") for field in ITEM_METRIC_FIELDS),
    )


def prescription_item_constraints(prefix: str):
    return (
        CheckConstraint("position >= 0", name=f"ck_{prefix}_position"),
        *(CheckConstraint(f"jsonb_typeof({field}) = 'object'", name=f"ck_{prefix}_{field}")
          for field in ("exercise_snapshot", "prescription")),
    )


async def build_food_item(session: AsyncSession, user_id: PyUUID, payload) -> dict[str, Any]:
    from domains.catalog.models import FoodItem

    item = FoodPortionInput.model_validate(payload)
    food = await FoodItem.get_visible_by_id(session, item.food_id, user_id=user_id)
    if food is None:
        raise HTTPException(404, "Food not found")
    factor = portion_factor(food, item.unit, item.quantity)
    values = {
        field: (getattr(food, field) * factor).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if getattr(food, field) is not None and factor is not None else None
        for field in NUTRIENT_FIELDS
    }
    totals = NutritionTotals.model_validate(values).model_dump()
    return {
        **item.model_dump(), **totals,
        "food_snapshot": FoodRead.model_validate(food).model_dump(mode="json"),
        # Đây là thông tin theo khẩu phần của catalog, không phải tổng đã nhân tỉ lệ không có kiểu.
        "nutrition_information": {"basis": "catalog_serving", "values": food.nutrition_information},
        "nutrition_incomplete": any(value is None for value in totals.values()),
    }


def portion_factor(food, unit: str, quantity: Decimal) -> Decimal | None:
    """Hệ số từ căn cứ dinh dưỡng đã lưu sang lượng đã ghi.

    Mọi thực phẩm lưu giá trị theo serving_size gam hoặc mililít, và lượng ăn được ghi
    bằng chính đơn vị đó; "1 tô", "1 suất" được quy ra gam/ml (theo portions) trước khi ghi.
    """
    known = any(getattr(food, field) is not None for field in NUTRIENT_FIELDS)
    if unit != food.serving_unit:
        raise HTTPException(422, "Portion unit must match the food serving unit; density is not inferred")
    if known and food.serving_size is None:
        raise HTTPException(422, "Nutrition requires a known serving basis")
    return quantity / food.serving_size if food.serving_size else None


async def _visible_exercise(session: AsyncSession, user_id: PyUUID, exercise_id, kind):
    from domains.catalog.models import Exercise

    exercise = await Exercise.get_visible_by_id(session, exercise_id, user_id=user_id)
    if exercise is None:
        raise HTTPException(404, "Exercise not found")
    if kind != exercise.kind:
        raise HTTPException(422, "Performance kind must match the exercise")
    return exercise


async def build_exercise_item(session: AsyncSession, user_id: PyUUID, payload, *, bodyweight_kg: float | None = None) -> dict[str, Any]:
    item = ExerciseActivityInput.model_validate(payload)
    exercise = await _visible_exercise(session, user_id, item.exercise_id, item.performance.kind)
    calorie = item.calorie_estimate.model_dump(mode="json")
    if item.calorie_estimate.kcal is None:
        # Giá trị từ người dùng/thiết bị luôn được ưu tiên; nếu không thì gắn một ước tính tái tạo được.
        calorie = estimate_kcal(item.performance, exercise.configuration, bodyweight_kg) or calorie
    metrics = item_metrics(item.performance, exercise.configuration, bodyweight_kg=bodyweight_kg)
    return {
        "exercise_id": exercise.id,
        "exercise_snapshot": ExerciseRead.model_validate(exercise).model_dump(mode="json"),
        "performance": item.performance.model_dump(mode="json"),
        "calorie_estimate": calorie,
        "energy_kcal": None if calorie.get("kcal") is None else Decimal(str(calorie["kcal"])),
        "kind": exercise.kind,
        **{field: None if metrics[field] is None else Decimal(str(metrics[field])) if field not in {"hard_sets", "working_sets"} else metrics[field]
           for field in ITEM_METRIC_FIELDS},
        "note": item.note,
    }


async def build_prescription_item(session: AsyncSession, user_id: PyUUID, payload) -> dict[str, Any]:
    item = ExercisePrescriptionInput.model_validate(payload)
    exercise = await _visible_exercise(session, user_id, item.exercise_id, item.prescription.kind)
    return {
        "exercise_id": exercise.id,
        "exercise_snapshot": ExerciseRead.model_validate(exercise).model_dump(mode="json"),
        "prescription": item.prescription.model_dump(mode="json"),
        "note": item.note,
    }


def sum_known(items, fields=NUTRIENT_FIELDS) -> dict[str, Decimal | None]:
    """Thành phần chưa biết làm tổng tương ứng thành chưa biết, không bao giờ là số 0."""
    return {
        field: sum((item[field] for item in items), Decimal(0))
        if all(item[field] is not None for item in items) else None
        for field in fields
    }


# --------------------------------------------------------------------------------------------------
# basemodel
# --------------------------------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def uuid7(_ctx: Any | None = None) -> uuid.UUID:
    """Tạo UUID version 7, tối ưu sắp xếp"""
    try:
        import uuid6

        return uuid6.uuid7()
    except ImportError:
        import os
        import time

        timestamp_ms = int(time.time() * 1000)
        rand = bytearray(os.urandom(10))
        # Phiên bản 7 (0111) ở các bit 48..51
        rand[0] = (rand[0] & 0x0F) | 0x70
        # Biến thể 1 (10) ở các bit 64..65
        rand[2] = (rand[2] & 0x3F) | 0x80
        raw_bytes = timestamp_ms.to_bytes(6, byteorder="big") + bytes(rand)
        return uuid.UUID(bytes=raw_bytes)


class BaseModel(Base):
    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    version_id: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    __mapper_args__ = {"version_id_col": version_id}

    @classmethod
    def get_columns(cls) -> list[str]:
        return [column.name for column in cls.__table__.columns]

    @classmethod
    def select_fields(cls, fields: Sequence[str] | None = None) -> list[Any]:
        if fields is None:
            return [getattr(cls, column) for column in cls.get_columns()]

        invalid_fields = set(fields) - set(cls.get_columns())
        if invalid_fields:
            invalid = ", ".join(sorted(invalid_fields))
            raise ValueError(f"Unknown fields for {cls.__name__}: {invalid}")
        return [getattr(cls, column) for column in fields]

    @classmethod
    def handle_select(cls, **kwargs: Any) -> Select:
        fields = kwargs.get("fields")
        if fields:
            return select(*cls.select_fields(fields))
        return select(cls)

    # Xử lý scope is_active cho các truy vấn 
    @classmethod
    def apply_active_scope(
        cls,
        query: Select,
        *,
        include_inactive: bool = False,
        is_active: bool | None = None,
    ) -> Select:
        if is_active is not None:
            return query.where(cls.is_active.is_(is_active))
        if not include_inactive:
            return query.where(cls.is_active.is_(True))
        return query

    @classmethod
    def handle_find(cls, query: Select, **kwargs: Any) -> Select:
        reserved_keys = {
            "fields",
            "include_inactive",
            "is_active",
            "order_by",
            "raise_error",
        }
        column_names = set(cls.get_columns())

        query = cls.apply_active_scope(
            query,
            include_inactive=bool(kwargs.get("include_inactive", False)),
            is_active=kwargs.get("is_active"),
        )

        for key, value in kwargs.items():
            if key in reserved_keys or value is None:
                continue
            if key == "ids":
                query = query.where(cls.id.in_(value))
            elif key in column_names:
                column = getattr(cls, key)
                if isinstance(value, (list, tuple, set)):
                    query = query.where(column.in_(value))
                else:
                    query = query.where(column == value)

        return query

    @classmethod
    def handle_order(cls, query: Select, **kwargs: Any) -> Select:
        order_by = OrderBy.model_validate(kwargs.get("order_by") or {"id": "asc"}).root

        clauses = []
        for column_name, direction in order_by.items():
            column = getattr(cls, column_name, None)
            if column is None:
                raise ValueError(
                    f"Column '{column_name}' does not exist in {cls.__name__}"
                )

            clauses.append(asc(column) if direction == "asc" else desc(column))

        return query.order_by(*clauses)

    @classmethod
    async def get_list(cls, session: AsyncSession, **kwargs: Any) -> list[Any]:
        query = cls.handle_select(**kwargs)
        query = cls.handle_find(query, **kwargs)
        query = cls.handle_order(query, **kwargs)

        result = await session.execute(query)
        if kwargs.get("fields"):
            return list(result.mappings().all())
        return list(result.scalars().unique().all())

    @classmethod
    async def get_one(cls, session: AsyncSession, **kwargs: Any) -> Any | None:
        query = cls.handle_select(**kwargs)
        query = cls.handle_find(query, **kwargs)
        query = cls.handle_order(query, **kwargs).limit(1)

        result = await session.execute(query)
        record = (
            result.mappings().first()
            if kwargs.get("fields")
            else result.scalars().unique().first()
        )
        if kwargs.get("raise_error") and record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{cls.__tablename__} not found",
            )
        return record

    @classmethod
    async def get_by_id(
        cls,
        session: AsyncSession,
        entity_id: uuid.UUID,
        **kwargs: Any,
    ) -> Self | None:
        return await cls.get_one(session, id=entity_id, **kwargs)

    @classmethod
    def _column_values(cls, values: Mapping[str, Any]) -> dict[str, Any]:
        column_names = set(cls.get_columns())
        return {key: value for key, value in values.items() if key in column_names}

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        payload: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Self:
        values = cls._column_values({**(payload or {}), **kwargs})
        values["is_active"] = True
        entity = cls(**values)
        session.add(entity)
        await session.flush()
        await session.refresh(entity)
        return entity

    # ------------------------------------------------------------------
    # Dữ liệu thuộc về một người dùng (model có cột user_id)
    # ------------------------------------------------------------------
    @classmethod
    def _user_query(cls, user_id: uuid.UUID, *, include_inactive: bool = False) -> Select:
        user_id = UserScope(user_id=user_id).user_id
        return cls.apply_active_scope(
            select(cls).where(cls.user_id == user_id), include_inactive=include_inactive,
        )

    @classmethod
    async def get_for_user(
        cls,
        session: AsyncSession,
        entity_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        include_inactive: bool = False,
    ) -> Self | None:
        result = await session.execute(
            cls._user_query(user_id, include_inactive=include_inactive).where(cls.id == entity_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def list_for_user(
        cls,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50,
        include_inactive: bool = False,
    ) -> list[Self]:
        options = Pagination(offset=offset, limit=limit, include_inactive=include_inactive)
        result = await session.execute(
            cls._user_query(user_id, include_inactive=options.include_inactive)
            .order_by(cls.created_at.desc(), cls.id.desc())
            .offset(options.offset).limit(options.limit)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Xóa mềm
    # ------------------------------------------------------------------
    @classmethod
    async def _set_active(cls, session: AsyncSession, entity: Self, active: bool) -> None:
        if entity.is_active != active:
            entity.is_active = active
            await session.flush()
            await session.refresh(entity)

    async def _before_deactivate(self, session: AsyncSession) -> None:
        """Hook cho lớp con cần dọn dẹp (kết thúc kế hoạch, ...) trước khi xóa mềm."""

    @classmethod
    async def soft_delete_for_user(
        cls,
        session: AsyncSession,
        entity_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        expected_version_id: int | None = None,
    ) -> Self | None:
        async with session.begin_nested():
            if await try_lock_user(session, user_id) is None:
                return None
            result = await session.execute(
                cls._user_query(user_id, include_inactive=True).where(cls.id == entity_id)
                .with_for_update().execution_options(populate_existing=True)
            )
            entity = result.scalar_one_or_none()
            if entity is None:
                return None
            if expected_version_id is not None:
                require_version(entity, expected_version_id)
            if entity.is_active:
                await entity._before_deactivate(session)
                await cls._set_active(session, entity, False)
        return entity


# --------------------------------------------------------------------------------------------------
# Hành vi dùng chung cho danh mục hệ thống/tuỳ chỉnh (thực phẩm và bài tập).
# --------------------------------------------------------------------------------------------------

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


# --------------------------------------------------------------------------------------------------
# Hàm hỗ trợ lưu trữ nhỏ dùng chung cho các model aggregate thuộc người dùng.
# --------------------------------------------------------------------------------------------------

async def try_lock_user(session: AsyncSession, user_id: PyUUID):
    """Khoá dòng User đang hoạt động cho transaction này; None khi không tồn tại."""
    from domains.identity.models import User

    user_id = UserScope(user_id=user_id).user_id
    await session.flush()
    result = await session.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
        .with_for_update().execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def lock_user(session: AsyncSession, user_id: PyUUID):
    user = await try_lock_user(session, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


def require_version(entity, expected_version_id: int) -> None:
    expected = VersionCheck(expected_version_id=expected_version_id).expected_version_id
    if entity.version_id != expected:
        raise HTTPException(409, "Version has changed; reload before editing")


def guard_immutable(cls, allowed=()) -> None:
    """Chốt bảo vệ ORM; bên gọi sửa aggregate lịch sử bằng cách thay thế chúng."""
    allowed = set(allowed) | {"is_active", "updated_at", "version_id"}

    def protect(_mapper, _connection, entity):
        state = inspect(entity)
        if any(state.attrs[column.key].history.has_changes()
               for column in state.mapper.column_attrs if column.key not in allowed):
            raise ValueError(f"{cls.__name__} snapshots are immutable; replace the aggregate")

    event.listen(cls, "before_update", protect)


# --------------------------------------------------------------------------------------------------
# Aggregate hoạt động thực tế bất biến với sửa nguyên tử và lệnh đọc có phạm vi.
#
# Tách ra từ models.journals trong đợt tổ chức lại theo miền.
# --------------------------------------------------------------------------------------------------

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
        from domains.goals_plans.models import TrainingPlan, TrainingPlanEntry

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
