"""Visible catalog reads and versioned custom catalog writes."""

from models.foods import FoodItem
from services.common import UserService, require_found


class CatalogService(UserService):
    async def list(self, model, options):
        return await model.list_visible(self.session, user_id=self.user_id, **options.model_dump())

    async def get(self, model, entity_id, *, include_inactive=False):
        return require_found(await model.get_visible_by_id(
            self.session, entity_id, user_id=self.user_id, include_inactive=include_inactive,
        ), model.__name__)

    async def create(self, model, payload):
        return await model.create_custom(self.session, user_id=self.user_id, payload=payload.to_payload())

    async def update(self, model, entity_id, payload):
        kwargs = {"payload": payload}
        if model is FoodItem:
            kwargs = {"payload": payload.to_payload(), "expected_version_id": payload.expected_version_id}
        return require_found(await model.update_custom(
            self.session, entity_id, user_id=self.user_id, **kwargs,
        ), model.__name__)

    async def set_active(self, model, entity_id, expected_version_id, *, active):
        action = model.restore_custom if active else model.soft_delete_custom
        return require_found(await action(
            self.session, entity_id, user_id=self.user_id, expected_version_id=expected_version_id,
        ), model.__name__)
