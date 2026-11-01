"""Authenticated profile, measurement history and goal use cases.

Models own persistence rules; the request transaction owns commit/rollback.
"""

from uuid import UUID

from pydantic import ValidationError

from domains.body.models.body_metrics import BodyMetric
from domains.goals_plans.models.goal import Goal
from domains.identity.models.user import User
from domains.body.schemas.body_metrics import BodyMetricCreate, BodyMetricQuery
from domains.shared.schemas.common import JsonObject, Pagination
from domains.goals_plans.schemas.goal import GoalCreate, GoalUpdateRequest
from domains.identity.schemas.user import OnboardingInput, UserUpdate

from domains.shared.services.common import UserService, require_found, request_validation_error


class UserDataService(UserService):

    async def update_profile(self, payload: UserUpdate) -> User:
        return require_found(
            await User.update_profile(self.session, self.user_id, payload), "User",
        )

    async def merge_personal_info(self, values: JsonObject) -> User:
        return require_found(
            await User.update_personal_info(self.session, self.user_id, values), "User",
        )

    async def onboard(self, payload: OnboardingInput) -> User:
        return require_found(
            await User.complete_onboarding(self.session, self.user_id, payload), "User",
        )

    async def delete_profile(self) -> None:
        require_found(await User.deactivate_profile(self.session, self.user_id), "User")

    async def create_metric(self, payload: BodyMetricCreate) -> BodyMetric:
        from domains.shared import write_hooks

        metric = await BodyMetric.create_snapshot(self.session, user_id=self.user_id, payload=payload)
        await write_hooks.emit(self.session, self.user_id, "BodyMetric", metric, "CREATE")
        return metric

    async def list_metrics(self, options: BodyMetricQuery) -> list[BodyMetric]:
        return await BodyMetric.list_for_user(
            self.session, user_id=self.user_id, **options.model_dump(),
        )

    async def latest_metric(self) -> BodyMetric:
        return require_found(
            await BodyMetric.get_latest_for_user(self.session, user_id=self.user_id), "Body metric",
        )

    async def get_metric(self, metric_id: UUID) -> BodyMetric:
        from domains.identity.consent import device_access

        metric = require_found(
            await BodyMetric.get_for_user(self.session, metric_id, user_id=self.user_id), "Body metric",
        )
        if metric.source != "MANUAL" and not await device_access(self.session, self.user_id):
            require_found(None, "Body metric")
        return metric

    async def replace_metric(self, metric_id: UUID, payload: BodyMetricCreate) -> BodyMetric:
        from domains.shared import write_hooks

        metric = require_found(await BodyMetric.replace_for_user(
            self.session, metric_id, user_id=self.user_id, payload=payload,
        ), "Body metric")
        await write_hooks.emit(self.session, self.user_id, "BodyMetric", metric, "UPDATE", replaces_id=metric_id)
        return metric

    async def delete_metric(self, metric_id: UUID) -> None:
        require_found(await BodyMetric.soft_delete_for_user(
            self.session, metric_id, user_id=self.user_id,
        ), "Body metric")

    async def confirm_goal(self, payload: GoalCreate) -> Goal:
        # A confirmed goal enters IN_PROGRESS; drafts remain on the client.
        return await Goal.create_for_user(self.session, user_id=self.user_id, payload=payload)

    async def list_goals(self, options: Pagination) -> list[Goal]:
        return await Goal.list_for_user(self.session, user_id=self.user_id, **options.model_dump())

    async def current_goal(self) -> Goal:
        return require_found(
            await Goal.get_current_for_user(self.session, user_id=self.user_id), "Goal",
        )

    async def get_goal(self, goal_id: UUID) -> Goal:
        return require_found(
            await Goal.get_for_user(self.session, goal_id, user_id=self.user_id), "Goal",
        )

    async def update_goal(self, goal_id: UUID, payload: GoalUpdateRequest) -> Goal:
        try:
            goal = await Goal.update_for_user(
                self.session, goal_id, user_id=self.user_id,
                payload=payload.to_payload(), expected_version_id=payload.expected_version_id,
            )
        except ValidationError as exc:
            # Includes validation against dates already stored in the database.
            raise request_validation_error(exc, "body") from exc
        return require_found(goal, "Goal")

    async def complete_goal(self, goal_id: UUID) -> Goal:
        return require_found(
            await Goal.complete_for_user(self.session, goal_id, user_id=self.user_id), "Goal",
        )

    async def cancel_goal(self, goal_id: UUID) -> Goal:
        return require_found(
            await Goal.cancel_for_user(self.session, goal_id, user_id=self.user_id), "Goal",
        )

    async def delete_goal(self, goal_id: UUID) -> None:
        require_found(
            await Goal.soft_delete_for_user(self.session, goal_id, user_id=self.user_id), "Goal",
        )
