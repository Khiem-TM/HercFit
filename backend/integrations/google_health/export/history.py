"""GH_HISTORY_EXPORT: người dùng yêu cầu tường minh gửi các bản ghi tạo trước khi bật nhóm."""
from __future__ import annotations
from uuid import UUID

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
LIMIT = 200


async def history_export(ctx: Context) -> None:
    job = ctx.job
    group = job.payload["group"]
    captured = int((job.progress or {}).get("captured", 0))
    index = int((job.progress or {}).get("model", 0))
    after = (job.progress or {}).get("after")
    models = GROUP_MODELS.get(group, [])
    async with fenced(job) as session:
        from domains.shared.models.domain import lock_user
        await lock_user(session, job.user_id)
        if index < len(models):
            model, aggregate = models[index]
            query = select(model).where(model.user_id == job.user_id, model.is_active.is_(True))
            if hasattr(model, "source"):
                query = query.where(model.source != "GOOGLE_HEALTH")
            if after:
                query = query.where(model.id > UUID(after))
            entities = list((await session.execute(query.order_by(model.id).limit(LIMIT))).scalars())
            for entity in entities:
                captured += await capture(session, job.user_id, aggregate, entity, "CREATE", history=True,
                                          operation_id=job.operation_id)
            if len(entities) == LIMIT:
                after = str(entities[-1].id)
            else:
                index, after = index + 1, None
        if index < len(models):
            await queue.requeue(session, job, {"model": index, "after": after, "captured": captured})
        else:
            await queue.complete(session, job, {"captured": captured})


HANDLERS = {"GH_HISTORY_EXPORT": history_export}
