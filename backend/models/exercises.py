"""System/custom exercise catalogue with scoped writes and optimistic versions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID as PyUUID

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy import (
    CheckConstraint, Enum, ForeignKey, Index, Select, String, Text,
    and_, event, inspect, or_, select, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from models.basemodel import BaseModel, uuid7
from models.foods import normalize_food_text
from schemas.common import UserScope, VersionCheck
from schemas.enums import FoodSourceType
from schemas.exercises import (
    ExerciseConfiguration, ExerciseCreate, ExerciseKind, ExerciseQuery,
    ExerciseUpdateRequest, SystemExerciseCreate,
)

if TYPE_CHECKING:
    from models.user import User

_configuration_adapter = TypeAdapter(ExerciseConfiguration)


class Exercise(BaseModel):
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
    normalized_name_vi: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_search_text: Mapped[str] = mapped_column(Text, nullable=False)

    owner: Mapped[User | None] = relationship("User")

    @classmethod
    def _custom_scope(cls, user_id: PyUUID) -> Any:
        user_id = UserScope(user_id=user_id).user_id
        return and_(cls.source_type == FoodSourceType.CUSTOM, cls.owner_user_id == user_id)

    @classmethod
    def _visible_query(cls, user_id: PyUUID, *, include_inactive: bool = False) -> Select:
        from models.user import User

        user_id = UserScope(user_id=user_id).user_id
        query = select(cls).where(
            select(User.id).where(User.id == user_id, User.is_active.is_(True)).exists(),
            or_(cls.source_type == FoodSourceType.SYSTEM, cls._custom_scope(user_id)),
        )
        return cls.apply_active_scope(query, include_inactive=include_inactive)

    @classmethod
    async def _lock_user(cls, session: AsyncSession, user_id: PyUUID) -> bool:
        from models.user import User

        user_id = UserScope(user_id=user_id).user_id
        await session.flush()
        result = await session.execute(
            select(User.id).where(User.id == user_id, User.is_active.is_(True)).with_for_update()
        )
        return result.scalar_one_or_none() is not None

    @classmethod
    async def get_visible_by_id(
        cls, session: AsyncSession, exercise_id: PyUUID, *, user_id: PyUUID,
        include_inactive: bool = False,
    ) -> Exercise | None:
        result = await session.execute(
            cls._visible_query(user_id, include_inactive=include_inactive).where(cls.id == exercise_id)
        )
        return result.scalar_one_or_none()

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
        if options.search and (normalized := normalize_food_text(options.search)):
            query = query.where(cls.normalized_search_text.contains(normalized, autoescape=True))
        if options.source_type is not None:
            query = query.where(cls.source_type == options.source_type)
        if options.kind is not None:
            query = query.where(cls.kind == options.kind)
        result = await session.execute(
            query.order_by(cls.normalized_name_vi, cls.id).offset(options.offset).limit(options.limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def create_custom(
        cls, session: AsyncSession, *, user_id: PyUUID,
        payload: ExerciseCreate | Mapping[str, Any],
    ) -> Exercise:
        user_id = UserScope(user_id=user_id).user_id
        values = ExerciseCreate.model_validate(payload).model_dump(mode="json")
        values["code"] = values["code"] or str(uuid7())
        async with session.begin_nested():
            if not await cls._lock_user(session, user_id):
                raise HTTPException(status_code=404, detail="User not found")
            exercise = await cls.create(session, {
                **values, "source_type": FoodSourceType.CUSTOM, "owner_user_id": user_id,
            })
        return exercise

    @classmethod
    async def create_system(
        cls, session: AsyncSession, *, payload: SystemExerciseCreate | Mapping[str, Any],
    ) -> Exercise:
        values = SystemExerciseCreate.model_validate(payload).model_dump(mode="json")
        async with session.begin_nested():
            exercise = await cls.create(session, {
                **values, "source_type": FoodSourceType.SYSTEM, "owner_user_id": None,
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
        if not await cls._lock_user(session, user_id):
            return None
        query = cls.apply_active_scope(
            select(cls).where(cls.id == exercise_id, cls._custom_scope(user_id)),
            include_inactive=include_inactive,
        )
        result = await session.execute(query.with_for_update().execution_options(populate_existing=True))
        return result.scalar_one_or_none()

    @staticmethod
    def _check_version(exercise: Exercise, expected_version_id: int) -> None:
        if exercise.version_id != expected_version_id:
            raise HTTPException(status_code=409, detail="Exercise version has changed; reload before editing")

    @classmethod
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
            cls._check_version(exercise, request.expected_version_id)
            if "configuration" in values and values["configuration"]["kind"] != exercise.kind:
                raise HTTPException(422, "configuration.kind must match exercise kind")
            for key, value in values.items():
                setattr(exercise, key, value)
            await session.flush()
            await session.refresh(exercise)
        return exercise

    @classmethod
    async def _set_custom_active(
        cls, session: AsyncSession, exercise_id: PyUUID, *, user_id: PyUUID,
        active: bool, expected_version_id: int,
    ) -> Exercise | None:
        version = VersionCheck(expected_version_id=expected_version_id).expected_version_id
        async with session.begin_nested():
            exercise = await cls._get_custom_for_update(
                session, exercise_id, user_id=user_id, include_inactive=True,
            )
            if exercise is None:
                return None
            cls._check_version(exercise, version)
            if exercise.is_active != active:
                exercise.is_active = active
                await session.flush()
                await session.refresh(exercise)
        return exercise

    @classmethod
    async def soft_delete_custom(
        cls, session: AsyncSession, exercise_id: PyUUID, *, user_id: PyUUID,
        expected_version_id: int,
    ) -> Exercise | None:
        return await cls._set_custom_active(
            session, exercise_id, user_id=user_id, active=False, expected_version_id=expected_version_id,
        )

    @classmethod
    async def restore_custom(
        cls, session: AsyncSession, exercise_id: PyUUID, *, user_id: PyUUID,
        expected_version_id: int,
    ) -> Exercise | None:
        return await cls._set_custom_active(
            session, exercise_id, user_id=user_id, active=True, expected_version_id=expected_version_id,
        )


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
    exercise.normalized_name_vi = normalize_food_text(exercise.name_vi or "")
    exercise.normalized_name_en = normalize_food_text(exercise.name_en) if exercise.name_en else None
    exercise.normalized_search_text = normalize_food_text(" ".join(
        value for value in (
            exercise.code, exercise.name_vi, exercise.name_en, exercise.instructions,
            *(exercise.equipment or []), *(exercise.muscle_groups or []),
        ) if value
    ))
