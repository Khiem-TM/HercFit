"""Service nghiệp vụ của miền dùng chung."""

from typing import TypeVar

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from domains.identity.models import User

# --------------------------------------------------------------------------------------------------
# Ngữ cảnh request dùng chung và chuyển đổi HTTP cho service của các miền.
# --------------------------------------------------------------------------------------------------

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


# --------------------------------------------------------------------------------------------------
# Cùng các use case ảnh chụp nguyên tử phục vụ bữa ăn và buổi tập.
# --------------------------------------------------------------------------------------------------

class JournalService(UserService):
    async def list(self, model, options):
        return await model.list_for_user(self.session, user_id=self.user_id, query=options)

    async def get(self, model, entity_id, *, include_inactive=False):
        return require_found(await model.get_for_user(
            self.session, entity_id, user_id=self.user_id, include_inactive=include_inactive,
        ), model.__name__)

    async def create(self, model, payload):
        from domains.shared import write_hooks

        entity = await model.create_snapshot(self.session, user_id=self.user_id, payload=payload)
        await write_hooks.emit(self.session, self.user_id, model.__name__, entity, "CREATE")
        return entity

    async def replace(self, model, entity_id, payload):
        from domains.shared import write_hooks

        entity = require_found(await model.replace_for_user(
            self.session, entity_id, user_id=self.user_id, payload=payload,
            expected_version_id=payload.expected_version_id,
        ), model.__name__)
        await write_hooks.emit(self.session, self.user_id, model.__name__, entity, "UPDATE", replaces_id=entity_id)
        return entity

    async def delete(self, model, entity_id, expected_version_id):
        require_found(await model.soft_delete_for_user(
            self.session, entity_id, user_id=self.user_id, expected_version_id=expected_version_id,
        ), model.__name__)
