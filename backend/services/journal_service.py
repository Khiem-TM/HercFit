"""The same atomic snapshot use cases serve meals and trainings."""

from services.common import UserService, require_found


class JournalService(UserService):
    async def list(self, model, options):
        return await model.list_for_user(self.session, user_id=self.user_id, query=options)

    async def get(self, model, entity_id, *, include_inactive=False):
        return require_found(await model.get_for_user(
            self.session, entity_id, user_id=self.user_id, include_inactive=include_inactive,
        ), model.__name__)

    async def create(self, model, payload):
        return await model.create_snapshot(self.session, user_id=self.user_id, payload=payload)

    async def replace(self, model, entity_id, payload):
        return require_found(await model.replace_for_user(
            self.session, entity_id, user_id=self.user_id, payload=payload,
            expected_version_id=payload.expected_version_id,
        ), model.__name__)

    async def delete(self, model, entity_id, expected_version_id):
        require_found(await model.soft_delete_for_user(
            self.session, entity_id, user_id=self.user_id, expected_version_id=expected_version_id,
        ), model.__name__)
