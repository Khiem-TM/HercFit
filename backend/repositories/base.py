"""Base Repository providing shared SQLAlchemy AsyncSession helpers."""

from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic repository base class bound to an AsyncSession."""

    def __init__(self, db: AsyncSession, model: type[ModelType]) -> None:
        self.db = db
        self.model = model

