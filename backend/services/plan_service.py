"""Manual plans and schedule versions; transaction boundary stays at the HTTP layer."""

from models.plans import Plan
from schemas.plans import PlanCreate
from services.common import UserService, require_found


class PlanService(UserService):
    async def get(self, model, entity_id, *, include_inactive=False):
        return require_found(await model.get_for_user(
            self.session, entity_id, user_id=self.user_id, include_inactive=include_inactive,
        ), model.__name__)

    async def list(self, model, options, *, plan_id=None):
        if plan_id is not None:
            await self.get(Plan, plan_id, include_inactive=options.include_inactive)
        values = options.model_dump()
        values["plan_id"] = plan_id
        return await model.list_for_user(self.session, user_id=self.user_id, **values)

    async def current(self, model=Plan, *, plan_id=None):
        if plan_id is not None:
            await self.get(Plan, plan_id)
        # Return None to the router rather than raising: expiry must commit on a 404.
        return await model.get_current_for_user(self.session, user_id=self.user_id, plan_id=plan_id)

    @staticmethod
    def manual_payload(payload):
        return PlanCreate(**payload.to_payload(), source={"type": "USER"})

    async def create(self, model, payload, *, plan_id=None):
        kwargs = {"plan_id": plan_id} if model is not Plan else {}
        data = self.manual_payload(payload) if model is Plan else payload
        return await model.create_for_user(self.session, user_id=self.user_id, payload=data, **kwargs)

    async def replace(self, model, entity_id, payload):
        data = self.manual_payload(payload) if model is Plan else payload
        return require_found(await model.replace_for_user(
            self.session, entity_id, user_id=self.user_id, payload=data,
            expected_version_id=payload.expected_version_id,
        ), model.__name__)

    async def end(self, model, entity_id, payload):
        return require_found(await model.end_for_user(
            self.session, entity_id, user_id=self.user_id, **payload.model_dump(),
        ), model.__name__)

    async def delete(self, model, entity_id, expected_version_id):
        require_found(await model.soft_delete_for_user(
            self.session, entity_id, user_id=self.user_id, expected_version_id=expected_version_id,
        ), model.__name__)

    async def entries(self, model, entity_id, options):
        return await model.list_entries_for_user(
            self.session, entity_id, user_id=self.user_id, options=options,
        )
