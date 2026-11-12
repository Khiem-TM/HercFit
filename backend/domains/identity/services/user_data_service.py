"""Các use case hồ sơ, lịch sử số đo và mục tiêu đã xác thực.

Model sở hữu luật lưu trữ; transaction của request sở hữu commit/rollback.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError

from domains.body.models.body_metrics import BodyMetric
from domains.body.schemas.body_metrics import BodyMetricCreate, BodyMetricQuery
from domains.goals_plans.models.goal import Goal
from domains.goals_plans.schemas.goal import GoalCreate, GoalUpdateRequest
from domains.identity.models.user import User
from domains.identity.schemas.user import OnboardingInput, UserUpdate
from domains.shared.schemas.common import JsonObject, Pagination
from domains.shared.services.common import UserService, request_validation_error, require_found


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

    # Số đo Google có (ghi xuyên qua khi đã kết nối): cột HercFit → loại bản ghi Google.
    GOOGLE_FIELDS = (("weight_kg", "weight"), ("height_cm", "height"), ("body_fat_pct", "body-fat"))
    LOCAL_FIELDS = ("muscle_mass_kg", "chest_cm", "waist_cm", "hip_cm")

    async def create_metric(self, payload: BodyMetricCreate) -> Any:
        """Đã kết nối Google: cân nặng / chiều cao / mỡ lưu vào health_points (bản HercFit) rồi được đẩy lên Google
        sau commit; khối cơ và chỉ số khác Google không có vẫn lưu trong body_metrics. Chưa kết nối: lưu như trước."""
        from domains.body.services.readings import Reading
        from domains.health_records import ports

        data = BodyMetricCreate.model_validate(payload)
        written: dict[str, Any] = {}
        for column, kind in self.GOOGLE_FIELDS:
            value = getattr(data, column)
            if value is None:
                continue
            result = await ports.write(self.session, self.user_id, kind, {
                "value": float(value), "measured_at": data.recorded_at.isoformat()})
            if result is None:  # chưa kết nối Google
                return await BodyMetric.create_snapshot(self.session, user_id=self.user_id, payload=data)
            written[column] = result
        # Google không có khối cơ và vòng đo: giữ trong HercFit.
        local = {field: getattr(data, field) for field in self.LOCAL_FIELDS if getattr(data, field) is not None}
        row = None
        if local:
            row = await BodyMetric.create(self.session, {"user_id": self.user_id, "recorded_at": data.recorded_at,
                                                         **local, "additional_metrics": data.additional_metrics})
        # id luôn là của một bản ghi có thật (điểm Google đầu tiên đã ghi, hoặc dòng HercFit), không bao giờ ngẫu nhiên.
        record_id = next((written[column].get("id") for column, _kind in self.GOOGLE_FIELDS
                          if (written.get(column) or {}).get("id")), None) or (row.id if row is not None else None)
        now = datetime.now(timezone.utc)
        return Reading(id=record_id, user_id=self.user_id,
                       recorded_at=data.recorded_at, created_at=now, updated_at=now, source="MANUAL",
                       weight_kg=data.weight_kg, height_cm=data.height_cm, body_fat_pct=data.body_fat_pct,
                       muscle_mass_kg=data.muscle_mass_kg, chest_cm=data.chest_cm, waist_cm=data.waist_cm,
                       hip_cm=data.hip_cm, additional_metrics=data.additional_metrics, written_by_hercfit=True)

    async def list_metrics(self, options: BodyMetricQuery) -> list[Any]:
        return await BodyMetric.list_for_user(
            self.session, user_id=self.user_id, **options.model_dump(),
        )

    async def latest_metric(self) -> Any:
        return require_found(
            await BodyMetric.get_latest_for_user(self.session, user_id=self.user_id), "Body metric",
        )

    async def _google_reading(self, metric_id: UUID):
        """Số đo trên Google có id này (bản sao trong health_points), nếu có."""
        from domains.body.services import readings

        found = [item for item in await readings.google(self.session, self.user_id, limit=10_000)
                 if item.id == metric_id]
        return found[0] if found else None

    async def get_metric(self, metric_id: UUID) -> Any:
        metric = await BodyMetric.get_for_user(self.session, metric_id, user_id=self.user_id)
        return require_found(metric or await self._google_reading(metric_id), "Body metric")

    async def replace_metric(self, metric_id: UUID, payload: BodyMetricCreate) -> Any:
        from domains.health_records import ports

        reading = await self._google_reading(metric_id)
        if reading is None:
            return require_found(await BodyMetric.replace_for_user(
                self.session, metric_id, user_id=self.user_id, payload=payload,
            ), "Body metric")
        data = BodyMetricCreate.model_validate(payload)
        column, kind = next((column, kind) for column, kind in self.GOOGLE_FIELDS
                            if getattr(reading, column) is not None)
        if getattr(data, column) is None:
            raise HTTPException(422, f"{column} is required to edit this measurement")
        await ports.write(self.session, self.user_id, kind, {
            "value": float(getattr(data, column)), "measured_at": data.recorded_at.isoformat()}, point_id=metric_id)
        return require_found(await self._google_reading(metric_id), "Body metric")

    async def delete_metric(self, metric_id: UUID) -> None:
        from domains.health_records import ports

        reading = await self._google_reading(metric_id)
        if reading is None:
            require_found(await BodyMetric.soft_delete_for_user(
                self.session, metric_id, user_id=self.user_id,
            ), "Body metric")
            return
        kind = next(kind for column, kind in self.GOOGLE_FIELDS if getattr(reading, column) is not None)
        await ports.write(self.session, self.user_id, kind, point_id=metric_id, delete=True)

    async def confirm_goal(self, payload: GoalCreate) -> Goal:
        # Mục tiêu đã xác nhận chuyển sang IN_PROGRESS; bản nháp vẫn ở phía client.
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
            # Bao gồm kiểm tra với các ngày đã lưu trong database.
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
