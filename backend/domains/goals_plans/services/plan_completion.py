"""Tick một buổi trong lịch tập = ghi buổi tập thật, tính calo và đồng bộ Google Health.

* Bài STRENGTH → MỘT buổi gym trong nhật ký (Training, source_entry_id = buổi kế hoạch): số hiệp/reps theo mức
  chỉ định (reps tối thiểu), tạ chỉ khi lịch ghi kg. Backend ước tính calo; buổi gym tự đẩy lên Google sau commit.
* Bài ENDURANCE/SPORT → buổi thể thao lưu trong HercFit (health_points), đẩy lên Google sau commit khi có kết nối. Quãng
  đường/thời lượng suy từ chính các bước của lịch và pace mục tiêu (pace cụ thể, hoặc vùng pace của hồ sơ VĐV);
  không suy được thì bỏ qua kèm thông báo, không bịa số liệu.
* Mỗi buổi thể thao ghi trong savepoint riêng: lỗi (ví dụ trùng giờ) không chặn việc tick, chỉ thành thông báo.

Mọi bài đều là bản ghi catalog: plan chỉ lưu exercise_id đã kiểm tra, buổi tập dùng lại đúng các id đó.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from domains.goals_plans.models.plans import TrainingPlan
from domains.shared.models.basemodel import utc_now

# Bước không có pace cụ thể dùng vùng pace của loại bài (khởi động/hồi phục luôn là chạy nhẹ).
WORKOUT_ZONE = {"TEMPO": "T", "THRESHOLD": "T", "INTERVAL": "I", "HILL": "I", "RACE": "M", "PROGRESSION": "M"}


def strength_sets(prescription: dict[str, Any]) -> list[dict[str, Any]]:
    """Nhóm hiệp chỉ định "4 × 8–12 @60 kg" → 4 hiệp thực hiện 8 reps, 60 kg (không có kg thì để trống)."""
    sets = []
    for group in prescription.get("sets") or []:
        load = group.get("load") or {}
        value = {"set_type": group.get("set_type") or "WORKING", "reps": group.get("reps_min"),
                 "hold_seconds": group.get("hold_seconds"), "rest_seconds": group.get("rest_seconds"),
                 "rpe": group.get("rpe_target"), "rir": group.get("rir_target"), "tempo": group.get("tempo"),
                 "weight_kg": load.get("value") if load.get("mode") == "KG" else None,
                 "load_mode": "BODYWEIGHT" if load.get("mode") == "BODYWEIGHT" else None}
        sets.extend({key: item for key, item in value.items() if item is not None} for _ in range(group.get("count") or 1))
    return sets


def _pace(step: dict[str, Any], workout_type: str, zones: dict[str, list[int]] | None) -> float | None:
    """Giây/km mục tiêu của một bước: pace cụ thể, vùng pace, hoặc vùng mặc định của loại bài."""
    target = step.get("target") or {}
    bounds = [value for value in (target.get("low"), target.get("high")) if value is not None]
    if target.get("type") == "PACE" and bounds:
        return sum(float(value) for value in bounds) / len(bounds)
    if not zones:
        return None
    if target.get("type") == "PACE_ZONE":
        zone = target.get("zone")
    elif step.get("step_type", "WORK") == "WORK":
        zone = WORKOUT_ZONE.get(workout_type, "E")
    else:
        zone = "E"
    fast, slow = zones.get(zone) or (None, None)
    return (fast + slow) / 2 if fast and slow else None


def endurance_totals(prescription: dict[str, Any], zones: dict[str, list[int]] | None) -> tuple[float, float] | None:
    """(thời lượng giây, quãng đường mét) của bài sức bền theo lịch; None khi thiếu pace để quy đổi."""
    seconds = meters = 0.0
    workout_type = prescription.get("workout_type") or "EASY"
    for block in prescription.get("steps") or []:
        for step in (block.get("steps") or []) * block["repeat"] if block.get("repeat") else [block]:
            pace = _pace(step, workout_type, zones)
            if step.get("duration_seconds"):
                seconds += float(step["duration_seconds"])
                if pace is None:
                    return None
                meters += float(step["duration_seconds"]) / pace * 1000
            else:
                meters += float(step["distance_meters"])
                if pace is None:
                    return None
                seconds += float(step["distance_meters"]) / 1000 * pace
    return (round(seconds), round(meters)) if seconds and meters else None


def _sport_performance(item, zones) -> dict[str, Any] | None:
    prescription = item.prescription or {}
    if prescription.get("kind") == "SPORT":
        return {"kind": "SPORT", "duration_seconds": prescription["duration_seconds"],
                "intensity": prescription.get("intensity") or "MODERATE"}
    totals = endurance_totals(prescription, zones)
    if totals is None:
        return None
    return {"kind": "ENDURANCE", "workout_type": prescription.get("workout_type") or "EASY",
            "duration_seconds": totals[0], "distance_meters": totals[1]}


async def complete_entry(service, schedule_id, entry_id) -> dict[str, Any] | None:
    """service là PlanService (session + user của request). Trả None khi không tìm thấy lịch/buổi."""
    from domains.catalog.schemas.exercises import StrengthPerformance
    from domains.health_records import ports
    from domains.shared.services.journal_service import JournalService
    from domains.training.models.trainings import Training
    from domains.training.schemas.trainings import TrainingCreate
    from domains.training.services.training_analytics import profile_read
    from domains.training.services.training_metrics import strength_duration

    session, user_id = service.session, service.user_id
    schedule, entry = await TrainingPlan.lock_entry_for_completion(session, schedule_id, entry_id, user_id=user_id)
    if entry is None:
        return None
    if entry.completed_at is not None:
        training_id = await session.scalar(select(Training.id).where(
            Training.user_id == user_id, Training.source_entry_id == entry.id, Training.is_active.is_(True)))
        return {"entry": entry, "training_id": training_id, "energy_kcal": None, "google_sessions": 0,
                "notices": ["Buổi này đã được ghi hoàn thành trước đó."]}

    notices: list[str] = []
    gym, sports = [], []
    zones = profile_read(service.user.personal_info).get("pace_zones")
    for item in entry.items:
        name = (item.exercise_snapshot or {}).get("name_vi") or "Bài tập"
        if item.exercise_id is None:
            notices.append(f"Bỏ qua {name}: bài tập không còn trong catalog.")
        elif (item.prescription or {}).get("kind") == "STRENGTH":
            gym.append({"exercise_id": str(item.exercise_id), "performance": {"kind": "STRENGTH", "sets": strength_sets(item.prescription)},
                        "note": item.note})
        elif (performance := _sport_performance(item, zones)) is not None:
            sports.append((name, item.exercise_id, performance))
        else:
            notices.append(f"Chưa ghi {name}: lịch không đủ pace để suy ra quãng đường; hãy ghi buổi chạy thực tế qua chat.")

    # Các phần của buổi xếp liền nhau và kết thúc ở thời điểm tick.
    gym_seconds = sum(strength_duration(StrengthPerformance.model_validate(item["performance"]))[0] for item in gym)
    cursor = utc_now() - timedelta(seconds=gym_seconds + sum(float(p["duration_seconds"]) for _, _, p in sports))
    result = {"entry": entry, "training_id": None, "energy_kcal": None, "google_sessions": 0, "notices": notices}
    energy = []
    if gym:
        training = await JournalService(session, service.user).create(Training, TrainingCreate(
            name=entry.label, started_at=cursor, timezone=schedule.timezone, source_entry_id=entry.id, items=gym,
            note=f"Ghi từ lịch tập {schedule.name}"))
        result["training_id"] = training.id
        energy.append(training.energy_kcal)
        cursor += timedelta(seconds=gym_seconds)
    for name, exercise_id, performance in sports:
        payload = {"name": f"{entry.label} · {name}", "started_at": cursor.isoformat(), "exercise_id": str(exercise_id),
                   "performance": performance, "timezone": schedule.timezone, "note": f"Ghi từ lịch tập {schedule.name}"}
        cursor += timedelta(seconds=float(performance["duration_seconds"]))
        try:
            async with session.begin_nested():
                written = await ports.write(session, user_id, "exercise", payload)
        except HTTPException as exc:
            detail = exc.detail.get("message") if isinstance(exc.detail, dict) else exc.detail
            notices.append(f"Chưa ghi {name}: {detail}")
            continue
        result["google_sessions"] += 1
        energy.append((written.get("derived") or {}).get("energy_kcal"))
    known = [float(value) for value in energy if value is not None]
    result["energy_kcal"] = round(sum(known), 1) if known else None
    if energy and len(known) < len(energy):
        notices.append("Chưa ước tính đủ calo: thêm cân nặng trong hồ sơ để backend tính calo tiêu hao.")
    entry.completed_at = utc_now()
    await session.flush()
    return result
