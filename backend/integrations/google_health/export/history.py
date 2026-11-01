"""GH_HISTORY_EXPORT: người dùng yêu cầu tường minh gửi các bản ghi tạo trước khi bật nhóm."""
from __future__ import annotations

from sqlalchemy import select

from core.database import get_db_session
from core.jobs import queue
from domains.body.models.body_metrics import BodyMetric
from domains.nutrition.models.logs import HydrationLog, NutritionLog
from domains.nutrition.models.meals import Meal
from domains.training.models.trainings import Training
from domains.wellbeing.models.logs import MenstrualPeriodLog, MoodLog, OvulationTestLog, SymptomLog
from integrations.google_health.export.capture import capture
from integrations.google_health.ingest.jobs import Context, fenced

GROUP_MODELS = {
    "body": [(BodyMetric, "BodyMetric")], "hydration": [(HydrationLog, "HydrationLog")],
    "nutrition": [(NutritionLog, "NutritionLog"), (Meal, "Meal")], "workout": [(Training, "Training")],
    "symptoms": [(SymptomLog, "SymptomLog")], "mood": [(MoodLog, "MoodLog")],
    "reproductive": [(MenstrualPeriodLog, "MenstrualPeriodLog"), (OvulationTestLog, "OvulationTestLog")],
}
LIMIT = 5000


async def history_export(ctx: Context) -> None:
    job = ctx.job
    group = job.payload["group"]
    captured = 0
    async with fenced(job) as session:
        for model, aggregate in GROUP_MODELS.get(group, []):
            query = select(model).where(model.user_id == job.user_id, model.is_active.is_(True))
            if hasattr(model, "source"):
                query = query.where(model.source != "GOOGLE_HEALTH")
            for entity in (await session.execute(query.limit(LIMIT))).scalars():
                captured += await capture(session, job.user_id, aggregate, entity, "CREATE", history=True,
                                          operation_id=job.operation_id)
        await queue.complete(session, job, {"captured": captured})


HANDLERS = {"GH_HISTORY_EXPORT": history_export}
