"""Shared request context and HTTP translation for domain services."""

from typing import TypeVar

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User

Entity = TypeVar("Entity")


def require_found(entity: Entity | None, name: str) -> Entity:
    if entity is None:
        raise HTTPException(404, f"{name} not found")
    return entity


def request_validation_error(exc: ValidationError, location: str) -> RequestValidationError:
    return RequestValidationError([
        {**error, "loc": (location, *error["loc"])}
        for error in exc.errors(include_context=False)
    ])


class UserService:
    def __init__(self, session: AsyncSession, user: User) -> None:
        self.session = session
        self.user = user
        self.user_id = user.id
