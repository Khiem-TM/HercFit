import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Self

from fastapi import HTTPException, status
from sqlalchemy import Boolean, DateTime, Integer, Select, asc, desc, func, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from models.domain import require_version, try_lock_user
from schemas.common import OrderBy, Pagination, UserScope


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
        # Version 7 (0111) in bits 48..51
        rand[0] = (rand[0] & 0x0F) | 0x70
        # Variant 1 (10) in bits 64..65
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
