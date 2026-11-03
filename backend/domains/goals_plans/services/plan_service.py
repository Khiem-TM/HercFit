"""Kế hoạch thủ công và phiên bản lịch; ranh giới transaction nằm ở tầng HTTP."""

from domains.goals_plans.models.plans import Plan, TrainingPlan
from domains.goals_plans.schemas.plans import PlanCreate
from domains.shared.services.common import UserService, require_found


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
        # Trả None cho router thay vì ném lỗi: việc hết hạn phải được commit khi trả 404.
        return await model.get_current_for_user(self.session, user_id=self.user_id, plan_id=plan_id)

    @staticmethod
    def manual_payload(payload):
        return PlanCreate(**payload.to_payload(), source={"type": "USER"})

    async def create(self, model, payload, *, plan_id=None):
        kwargs = {"plan_id": plan_id} if model is not Plan else {}
        data = self.manual_payload(payload) if model is Plan else payload
        return await model.create_for_user(self.session, user_id=self.user_id, payload=data, **kwargs)

    async def previous_training_plan(self):
        return await TrainingPlan.previous_for_user(self.session, user_id=self.user_id)

    async def create_training_plan(self, payload):
        return await TrainingPlan.create_with_parent(self.session, user_id=self.user_id, payload=payload)

    async def complete_entry(self, schedule_id, entry_id):
        from domains.goals_plans.services.plan_completion import complete_entry

        return require_found(await complete_entry(self, schedule_id, entry_id), "TrainingPlanEntry")

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
