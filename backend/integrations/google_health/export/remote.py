"""Apply an explicitly accepted remote edit without generating an export echo.

Immutable meals/workouts become a new aggregate-only snapshot. Their original
food items/sets remain on the historical snapshot; Google cannot reconstruct them.
"""
from fastapi import HTTPException
from sqlalchemy import select, text

from domains.body.models.body_metrics import BodyMetric
from domains.nutrition.models.meals import Meal
from domains.training.models.trainings import Training
from integrations.google_health.adapters import adapter
from integrations.google_health import projections
from integrations.google_health.export import mapping
from integrations.google_health.export.capture import mark_import
from integrations.google_health.export.history import GROUP_MODELS

MODELS = {aggregate: model for group in GROUP_MODELS.values() for model, aggregate in group}
META = {"id", "created_at", "updated_at", "version_id", "is_active"}


async def accept(session, user_id, row, remote):
    model = MODELS.get(row["aggregate_type"])
    if model is None:
        raise HTTPException(409, "Không có bộ chuyển đổi cho bản ghi này.")
    entity = (await session.execute(select(model).where(model.id == row["aggregate_id"], model.user_id == user_id,
                                                       model.is_active.is_(True)).with_for_update())).scalar_one_or_none()
    if entity is None:
        raise HTTPException(409, "Bản ghi đã được thay hoặc xoá; tải lại trước khi xử lý xung đột.")
    newer = (await session.execute(text("SELECT 1 FROM export_outbox WHERE mapping_id = :m "
        "AND created_at > (SELECT created_at FROM export_outbox WHERE id = :o) "
        "AND state NOT IN ('SUPERSEDED', 'FAILED') LIMIT 1"), {"m": row["mapping_id"], "o": row["outbox_id"]})).first()
    if newer:
        raise HTTPException(409, "Có thay đổi cục bộ mới hơn; giữ bản HercFit để gửi thay đổi mới nhất.")
    parsed = adapter().parse_point(row["data_type"], remote)
    if not parsed.clean or not parsed.time.physical_start:
        raise HTTPException(409, "Dữ liệu Google chưa đủ hợp lệ để thay bản cục bộ.")
    zone = getattr(entity, "timezone", "Asia/Ho_Chi_Minh")
    value = parsed.value
    if model is BodyMetric:
        projected = projections.body_row(parsed)
        column = {"weight": "weight_kg", "height": "height_cm", "body-fat": "body_fat_pct"}[row["data_type"]]
        changes = {column: projected[column], "recorded_at": projected["recorded_at"]} if projected else None
    elif model in (Meal,) or row["aggregate_type"] == "NutritionLog":
        projected = projections.nutrition_row(parsed, zone)
        changes = {key: projected[key] for key in ("consumed_at", "energy_kcal", "protein_g", "carbohydrate_g", "fat_g")} if projected else None
        if changes is not None:
            changes["name" if model is Meal else "food_name"] = projected.get("food_name") or getattr(entity, "name", None)
            if model is Meal:
                changes["nutrition_incomplete"] = any(changes[k] is None for k in ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g"))
            else:
                changes.update({key: projected[key] for key in ("ended_at", "local_date", "utc_offset_s", "meal_type", "nutrients", "serving")})
    elif model is Training:
        projected = projections.workout_row(parsed, zone)
        changes = {key: projected[key] for key in ("started_at", "ended_at", "energy_kcal")} if projected else None
        if changes is not None:
            changes["duration_seconds"] = projected["active_seconds"] or projected["elapsed_seconds"]
            changes.update(name=value.get("displayName") or entity.name,
                           discipline={v: k for k, v in mapping.DISCIPLINE_TYPES.items()}.get(value.get("exerciseType"), "MIXED"),
                           calories_incomplete=changes["energy_kcal"] is None, session_rpe=None, training_load=None)
    elif row["aggregate_type"] == "HydrationLog":
        projected = projections.hydration_row(parsed, zone)
        changes = {key: projected[key] for key in ("consumed_at", "amount_ml", "local_date")} if projected else None
    else:
        fields = {"SymptomLog": {"symptoms": "symptoms"}, "MoodLog": {"moods": "moods", "valences": "valences"},
                  "OvulationTestLog": {"result": "result"}, "MenstrualPeriodLog": {"note": "notes"}}
        changes = {local: value.get(key) for local, key in fields.get(row["aggregate_type"], {}).items()}
        changes["started_at" if row["aggregate_type"] == "MenstrualPeriodLog" else "recorded_at"] = parsed.time.physical_start
        changes["local_date"] = projections.civil_date(parsed, zone)
        if row["aggregate_type"] == "MenstrualPeriodLog":
            changes["ended_at"] = parsed.time.physical_end
    if changes is None:
        raise HTTPException(409, "Không chuyển đổi được dữ liệu Google; bản cục bộ được giữ nguyên.")
    await mark_import(session)
    if model in (BodyMetric, Meal, Training):
        values = {c.name: getattr(entity, c.name) for c in model.__table__.columns if c.name not in META}
        if model in (Meal, Training):
            values.update(replaces_id=entity.id, source="LEGACY_IMPORT", detail_status="AGGREGATE_ONLY")
        replacement = model(**{**values, **changes})
        if model in (Meal, Training):
            replacement.items = []
            entity.image_url = entity.image_public_id = None
        session.add(replacement)
        entity.is_active = False
        await session.flush()
        await session.execute(text("UPDATE google_resource_mappings SET aggregate_id = :new, updated_at = now() "
            "WHERE connection_id = :c AND aggregate_type = :t AND aggregate_id = :old"),
            {"new": replacement.id, "old": entity.id, "c": row["connection_id"], "t": row["aggregate_type"]})
        entity = replacement
    else:
        for key, value in changes.items():
            setattr(entity, key, value)
        await session.flush()
    from domains.analytics.services.jobs import enqueue
    await enqueue(session, user_id)
    return entity
