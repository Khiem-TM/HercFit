"""Phân tích tập luyện chỉ đọc trên chỉ số theo mục do server tính.

Truy vấn chỉ chiếu các cột suy ra (cộng JSON thành tích nhỏ cho
set nặng nhất/vòng chạy). Không gì ở đây được lưu; insight là các luật tất định
trả về kèm ngưỡng và bằng chứng của từng phát hiện.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import Date, func, select

from domains.training.models.trainings import Training, TrainingItem
from domains.goals_plans.models.plans import TrainingPlan, TrainingPlanEntry
from domains.catalog.schemas.exercises import HARD_WORKOUTS, StrengthSet, WorkoutType
from domains.shared.schemas.tracking import day_bounds
from domains.training.schemas.training import TrainingProfile
from domains.training.services.training_metrics import (
    effective_load,
    estimate_1rm,
    hr_zones,
    pace_zones,
    riegel,
    threshold_from_race,
)

ZERO = Decimal(0)
RACE_DISTANCES = {"1K": 1000, "5K": 5000, "10K": 10000, "HALF": 21097.5, "MARATHON": 42195}
REP_MAX_TARGETS = (1, 3, 5, 10)

# Ngưỡng của các luật (trả về như bằng chứng để agent trích dẫn).
ACWR_HIGH, ACWR_DANGER, ACWR_LOW = 1.3, 1.5, 0.8          # "Vùng tối ưu" 0.8-1.3 của Gabbett (2016)
WEEKLY_RUN_NOTICE, WEEKLY_RUN_WARNING = 0.10, 0.30        # hướng dẫn 10%; Nielsen và cộng sự (2014): rủi ro khi >30%
EASY_SHARE_MIN = 70.0                                     # phân bố phân cực ~80/20 của Seiler (2010)
HARD_SETS_LOW, HARD_SETS_HIGH = 10, 20                    # quan hệ liều-đáp ứng của số set mỗi tuần, Schoenfeld và cộng sự (2017)
MAX_CONSECUTIVE_DAYS = 7
ADHERENCE_MIN = 70.0
PROTEIN_G_PER_KG = (1.6, 2.2)                             # ISSN position stand (2017)
CARB_G_PER_KG_HIGH = (6, 10)                              # ACSM/AND/DC (2016): 1-3 giờ/ngày sức bền
CARB_G_PER_KG_MODERATE = (5, 7)                           # ~1 giờ/ngày vận động vừa
LONG_SESSION_SECONDS = 90 * 60


@dataclass
class Row:
    training_id: Any
    day: date
    discipline: str
    session_seconds: Decimal | None
    training_load: Decimal | None
    session_rpe: Decimal | None
    source_entry_id: Any
    kind: str | None
    exercise_id: Any
    snapshot: dict
    performance: dict
    duration_seconds: Decimal | None
    distance_meters: Decimal | None
    volume_kg: Decimal | None
    best_e1rm_kg: Decimal | None
    hard_sets: int | None
    energy_kcal: Decimal | None

    @property
    def activity(self) -> str | None:
        return (self.snapshot.get("configuration") or {}).get("activity")

    @property
    def is_run(self) -> bool:
        return self.kind == "ENDURANCE" and self.activity == "RUN"

    @property
    def name(self) -> str:
        return self.snapshot.get("name_vi") or "?"


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def today_in(zone: str) -> date:
    return datetime.now(ZoneInfo(zone)).date()


async def _rows(session, user_id, start: date, end: date, zone: str, *, exercise_id=None) -> list[Row]:
    lower, upper = day_bounds(start, end, zone)
    local_day = func.timezone(zone, Training.started_at).cast(Date)
    query = (
        select(Training.id, local_day, Training.discipline, Training.duration_seconds, Training.training_load,
               Training.session_rpe, Training.source_entry_id, TrainingItem.kind, TrainingItem.exercise_id,
               TrainingItem.exercise_snapshot, TrainingItem.performance, TrainingItem.duration_seconds,
               TrainingItem.distance_meters, TrainingItem.volume_kg, TrainingItem.best_e1rm_kg,
               TrainingItem.hard_sets, TrainingItem.energy_kcal)
        .join(TrainingItem, TrainingItem.training_id == Training.id)
        .where(Training.user_id == user_id, Training.is_active.is_(True),
               Training.started_at >= lower, Training.started_at < upper)
        .order_by(Training.started_at, TrainingItem.position)
    )
    if exercise_id is not None:
        query = query.where(TrainingItem.exercise_id == exercise_id)
    return [Row(*(row[:7]), row[7].value if row[7] is not None else None, *row[8:]) for row in (await session.execute(query)).all()]


# Bộ đọc v2 (training): buổi chạy từ thiết bị được đưa vào phân tích chạy bộ trừ khi có buổi nhập tay trùng.
RUN_EXERCISE_TYPES = frozenset({"RUNNING", "TRAIL_RUN", "INCLINE_RUN", "TREADMILL"})
SAME_SESSION_START_SECONDS = 15 * 60
SAME_SESSION_OVERLAP = 0.5


def _same_session(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Bắt đầu cách nhau trong 15 phút, hoặc chồng lên nhau một nửa thời lượng của buổi ngắn hơn."""
    if abs((a_start - b_start).total_seconds()) <= SAME_SESSION_START_SECONDS:
        return True
    overlap = (min(a_end, b_end) - max(a_start, b_start)).total_seconds()
    shorter = min((a_end - a_start).total_seconds(), (b_end - b_start).total_seconds())
    return shorter > 0 and overlap / shorter >= SAME_SESSION_OVERLAP


def is_device(row: Row) -> bool:
    return row.performance.get("source") == "device"


async def _device_runs(session, user_id, start: date, end: date, manual: list[Row]) -> list[Row]:
    """Các buổi chạy thiết bị ghi lại mà không có trong nhật ký HercFit (bộ đọc v2 `training`, consent thiết bị).

    Buổi nhập tay thắng khi trùng: nó mang RPE, loại bài và các vòng. Buổi từ thiết bị chỉ
    có những gì thiết bị đo (quãng đường, thời gian di chuyển, kcal); cường độ vẫn là chưa biết.
    """
    from core.flags import reader_v2
    from domains.health_records.models.device_records import DeviceWorkout
    from domains.identity import consent

    if not reader_v2("training") or not await consent.device_access(session, user_id):
        return []
    workouts = (await session.execute(select(DeviceWorkout).where(
        DeviceWorkout.user_id == user_id, DeviceWorkout.is_active.is_(True),
        DeviceWorkout.exercise_type.in_(RUN_EXERCISE_TYPES), DeviceWorkout.local_date >= start,
        DeviceWorkout.local_date <= end, DeviceWorkout.distance_m > 0,
    ).order_by(DeviceWorkout.started_at))).scalars().all()
    manual_ids = {row.training_id for row in manual}
    spans = [(started, started + timedelta(seconds=float(seconds or 0))) for started, seconds in (await session.execute(
        select(Training.started_at, Training.duration_seconds).where(Training.id.in_(manual_ids)))).all()] if manual_ids else []
    rows = []
    for workout in workouts:
        seconds = workout.active_seconds or workout.elapsed_seconds
        if not seconds or any(_same_session(workout.started_at, workout.ended_at, a, b) for a, b in spans):
            continue
        rows.append(Row(
            training_id=workout.id, day=workout.local_date, discipline="ENDURANCE", session_seconds=Decimal(seconds),
            training_load=None, session_rpe=None, source_entry_id=None, kind="ENDURANCE", exercise_id=None,
            snapshot={"name_vi": workout.display_name or "Chạy (thiết bị)", "configuration": {"activity": "RUN"}},
            performance={"source": "device", "duration_seconds": seconds, "moving_seconds": seconds},
            duration_seconds=Decimal(seconds), distance_meters=workout.distance_m, volume_kg=None, best_e1rm_kg=None,
            hard_sets=None, energy_kcal=workout.energy_kcal))
    return rows


async def _run_rows(session, user_id, start: date, end: date, zone: str) -> tuple[list[Row], list[Row]]:
    manual = [row for row in await _rows(session, user_id, start, end, zone) if row.is_run]
    return manual, await _device_runs(session, user_id, start, end, manual)


def _sessions(rows: list[Row]) -> dict[Any, Row]:
    """Dòng đầu tiên của mỗi buổi tập mang các trường cấp buổi."""
    first: dict[Any, Row] = {}
    for row in rows:
        first.setdefault(row.training_id, row)
    return first


async def _planned(session, user_id, start: date, end: date) -> tuple[dict[date, int], set]:
    """Các mục không phải nghỉ của lịch chưa xoá đến hạn trong khoảng, và id của chúng."""
    query = (
        select(TrainingPlanEntry.id, TrainingPlanEntry.scheduled_date)
        .join(TrainingPlan, TrainingPlan.id == TrainingPlanEntry.training_plan_id)
        .where(TrainingPlan.user_id == user_id, TrainingPlan.is_active.is_(True),
               TrainingPlanEntry.is_rest.is_(False),
               TrainingPlanEntry.scheduled_date >= start, TrainingPlanEntry.scheduled_date <= end)
    )
    per_week: dict[date, int] = defaultdict(int)
    ids = set()
    for entry_id, day in (await session.execute(query)).all():
        per_week[week_start(day)] += 1
        ids.add(entry_id)
    return per_week, ids


# ----------------------------------------------------------------- tóm tắt

async def summary(session, user_id, options) -> dict[str, Any]:
    rows = await _rows(session, user_id, options.start_date, options.end_date, options.timezone)
    # Buổi theo kế hoạch chỉ được tính khi đã đến hạn (không tính tương lai).
    due_end = min(options.end_date, today_in(options.timezone))
    planned, planned_ids = await _planned(session, user_id, options.start_date, due_end)
    weeks: dict[date, dict[str, Any]] = {}
    current = week_start(options.start_date)
    while current <= options.end_date:
        weeks[current] = {"week_start": current, "sessions": 0, "sessions_by_discipline": defaultdict(int), "training_load": ZERO,
                          "load_known": 0, "duration_seconds": ZERO, "energy_kcal": ZERO, "energy_unknown": False,
                          "run_distance_meters": ZERO, "run_duration_seconds": ZERO, "strength_volume_kg": ZERO,
                          "hard_sets_by_muscle": defaultdict(int), "completed": set()}
        current += timedelta(days=7)
    for row in _sessions(rows).values():
        week = weeks[week_start(row.day)]
        week["sessions"] += 1
        week["sessions_by_discipline"][row.discipline] += 1
        if row.training_load is not None:
            week["training_load"] += row.training_load
            week["load_known"] += 1
        if row.source_entry_id in planned_ids:
            week["completed"].add(row.source_entry_id)
    for row in rows:
        week = weeks[week_start(row.day)]
        week["duration_seconds"] += row.duration_seconds or ZERO
        if row.energy_kcal is None:
            week["energy_unknown"] = True
        else:
            week["energy_kcal"] += row.energy_kcal
        if row.is_run:
            week["run_distance_meters"] += row.distance_meters or ZERO
            week["run_duration_seconds"] += row.duration_seconds or ZERO
        if row.kind == "STRENGTH":
            week["strength_volume_kg"] += row.volume_kg or ZERO
            for muscle in row.snapshot.get("muscle_groups") or []:
                week["hard_sets_by_muscle"][muscle] += row.hard_sets or 0
    result = []
    for start, week in weeks.items():
        planned_count = planned.get(start, 0)
        completed = len(week["completed"])
        result.append({
            **{k: v for k, v in week.items() if k not in {"load_known", "energy_unknown", "completed"}},
            "sessions_by_discipline": dict(week["sessions_by_discipline"]),
            "hard_sets_by_muscle": dict(week["hard_sets_by_muscle"]),
            "training_load": week["training_load"] if week["load_known"] else None,
            "energy_kcal": None if week["energy_unknown"] else week["energy_kcal"],
            "run_pace_seconds_per_km": float(week["run_duration_seconds"] * 1000 / week["run_distance_meters"]) if week["run_distance_meters"] else None,
            "planned_sessions": planned_count, "completed_planned_sessions": completed,
            "adherence_pct": round(100 * completed / planned_count, 1) if planned_count else None,
        })
    return {"timezone": options.timezone, "start_date": options.start_date, "end_date": options.end_date, "weeks": result}


# ----------------------------------------------------------------- tải tập

async def daily_loads(session, user_id, start: date, end: date, zone: str) -> tuple[dict[date, Decimal], int]:
    lower, upper = day_bounds(start, end, zone)
    local_day = func.timezone(zone, Training.started_at).cast(Date).label("day")
    query = (select(local_day, func.coalesce(func.sum(Training.training_load), 0), func.count().filter(Training.training_load.is_(None)))
             .where(Training.user_id == user_id, Training.is_active.is_(True), Training.started_at >= lower, Training.started_at < upper)
             .group_by(local_day))
    loads, missing = {}, 0
    for day, load, unknown in (await session.execute(query)).all():
        loads[day] = Decimal(load)
        missing += unknown
    return loads, missing


def _rolling(loads: dict[date, Decimal], day: date, days: int) -> Decimal:
    return sum((loads.get(day - timedelta(days=offset), ZERO) for offset in range(days)), ZERO)


def _acwr(loads, day) -> tuple[Decimal, Decimal, float | None]:
    """ACWR trung bình trượt: tải 7 ngày so với tải 28 ngày quy về mỗi tuần."""
    acute = _rolling(loads, day, 7)
    chronic = _rolling(loads, day, 28) / 4
    return acute, chronic, round(float(acute / chronic), 2) if chronic else None


def _monotony(loads, day) -> tuple[float | None, float | None]:
    week = [float(loads.get(day - timedelta(days=offset), ZERO)) for offset in range(7)]
    if not any(week):
        return None, None
    deviation = statistics.pstdev(week)
    monotony = round(statistics.fmean(week) / deviation, 2) if deviation else None
    return monotony, round(sum(week) * monotony, 1) if monotony else None


async def load(session, user_id, options) -> dict[str, Any]:
    loads, missing = await daily_loads(session, user_id, options.start_date - timedelta(days=27), options.end_date, options.timezone)
    days, day = [], options.start_date
    while day <= options.end_date:
        acute, chronic, ratio = _acwr(loads, day)
        days.append({"date": day, "load": loads.get(day, ZERO), "acute_7d": acute, "chronic_28d_weekly": chronic, "acwr": ratio})
        day += timedelta(days=1)
    monotony, strain = _monotony(loads, options.end_date)
    return {"timezone": options.timezone, "start_date": options.start_date, "end_date": options.end_date, "days": days,
            "monotony_7d": monotony, "strain_7d": strain, "sessions_without_rpe": missing}


# ----------------------------------------------------------------- sức mạnh

def _top_set(performance: dict, bodyweight: float | None) -> dict | None:
    best = None
    for raw in performance.get("sets", []):
        work_set = StrengthSet.model_validate(raw)
        load_kg = effective_load(work_set, bodyweight)
        if work_set.set_type.value == "WARMUP" or not load_kg or not work_set.reps:
            continue
        candidate = {"load_kg": round(load_kg, 2), "reps": work_set.reps, "rpe": work_set.rpe}
        if best is None or (load_kg, work_set.reps) > (best["load_kg"], best["reps"]):
            best = candidate
    return best


async def strength_progress(session, user_id, options) -> dict[str, Any]:
    rows = await _rows(session, user_id, options.start_date, options.end_date, options.timezone, exercise_id=options.exercise_id)
    if not rows:
        from domains.catalog.models.exercises import Exercise
        exercise = await Exercise.get_visible_by_id(session, options.exercise_id, user_id=user_id)
        if exercise is None:
            raise HTTPException(404, "Exercise not found")
        name = exercise.name_vi
    else:
        name = rows[0].name
    by_training: dict[Any, dict] = {}
    for row in rows:
        entry = by_training.setdefault(row.training_id, {"date": row.day, "training_id": row.training_id, "best_e1rm_kg": None,
                                                         "volume_kg": ZERO, "hard_sets": 0, "top_set": None})
        if row.best_e1rm_kg is not None and (entry["best_e1rm_kg"] is None or row.best_e1rm_kg > entry["best_e1rm_kg"]):
            entry["best_e1rm_kg"] = row.best_e1rm_kg
        entry["volume_kg"] += row.volume_kg or ZERO
        entry["hard_sets"] += row.hard_sets or 0
        top = _top_set(row.performance, None)
        if top and (entry["top_set"] is None or (top["load_kg"], top["reps"]) > (entry["top_set"]["load_kg"], entry["top_set"]["reps"])):
            entry["top_set"] = top
    sessions = list(by_training.values())
    best = max((s["best_e1rm_kg"] for s in sessions if s["best_e1rm_kg"] is not None), default=None)
    return {"exercise_id": options.exercise_id, "exercise_name": name, "sessions": sessions, "best_e1rm_kg": best,
            "e1rm_change_pct_4w": _e1rm_change(sessions, options.end_date)}


def _e1rm_change(sessions, end: date) -> float | None:
    """e1RM tốt nhất trong 14 ngày gần nhất so với 14 ngày trước đó, tính theo phần trăm."""
    def best(lo, hi):
        values = [s["best_e1rm_kg"] for s in sessions if s["best_e1rm_kg"] is not None and lo <= s["date"] <= hi]
        return max(values, default=None)
    recent, earlier = best(end - timedelta(days=13), end), best(end - timedelta(days=27), end - timedelta(days=14))
    return round(float((recent - earlier) / earlier * 100), 1) if recent and earlier else None


async def strength_records(session, user_id, *, timezone: str, until: date | None = None) -> dict[str, Any]:
    until = until or today_in(timezone)
    rows = [r for r in await _rows(session, user_id, date(2000, 1, 1), until, timezone) if r.kind == "STRENGTH"]
    records: dict[Any, dict] = {}
    for row in rows:
        record = records.setdefault(row.exercise_id or row.name, {"exercise_id": row.exercise_id, "exercise_name": row.name,
                                                                   "best_e1rm_kg": None, "best_e1rm_date": None, "rep_maxes_kg": {}})
        if row.best_e1rm_kg is not None and (record["best_e1rm_kg"] is None or row.best_e1rm_kg > record["best_e1rm_kg"]):
            record["best_e1rm_kg"], record["best_e1rm_date"] = row.best_e1rm_kg, row.day
        for raw in row.performance.get("sets", []):
            work_set = StrengthSet.model_validate(raw)
            load_kg = effective_load(work_set)
            if work_set.set_type.value == "WARMUP" or not load_kg or not work_set.reps:
                continue
            for target in REP_MAX_TARGETS:
                current = record["rep_maxes_kg"].get(f"{target}RM")
                if work_set.reps >= target and (current is None or load_kg > current["load_kg"]):
                    record["rep_maxes_kg"][f"{target}RM"] = {"load_kg": round(load_kg, 2), "reps": work_set.reps, "date": row.day.isoformat()}
    ordered = sorted(records.values(), key=lambda r: -(r["best_e1rm_kg"] or 0))
    return {"records": ordered}


# ----------------------------------------------------------------- chạy bộ

NON_CONTINUOUS = frozenset({"INTERVAL", "FARTLEK", "HILL", "WALK_RUN"})


def _effort_candidates(row: Row) -> list[tuple[float, float]]:
    """Các buổi chạy liên tục trọn vẹn, cộng mọi chuỗi vòng WORK liên tiếp (ví dụ chạy thử 5x1K)."""
    performance = row.performance
    candidates = []
    if performance.get("workout_type") not in NON_CONTINUOUS:
        candidates.append((float(row.distance_meters), float(performance.get("moving_seconds") or performance["duration_seconds"])))
    laps = performance.get("laps", [])
    for start in range(len(laps)):
        distance = seconds = 0.0
        for lap in laps[start:]:
            if lap.get("lap_type", "WORK") != "WORK":
                break
            distance += lap["distance_meters"]
            seconds += lap["duration_seconds"]
            candidates.append((distance, seconds))
    return candidates


def _best_efforts(rows: list[Row]) -> dict[str, dict]:
    """Nỗ lực trong phạm vi 3% so với cự ly chuẩn; thời gian được quy đổi về đúng cự ly."""
    best: dict[str, dict] = {}
    for row in rows:
        if not row.is_run:
            continue
        candidates = _effort_candidates(row)
        for distance, seconds in candidates:
            for label, target in RACE_DISTANCES.items():
                if abs(distance - target) / target <= 0.03:
                    scaled = seconds * target / distance
                    if label not in best or scaled < best[label]["time_seconds"]:
                        best[label] = {"time_seconds": round(scaled), "date": row.day.isoformat(),
                                       "pace_seconds_per_km": round(scaled * 1000 / target, 1)}
    return best


def predictions(best_efforts: dict[str, dict], profile: TrainingProfile | None) -> dict[str, int] | None:
    """Công thức Riegel từ nỗ lực tham chiếu mạnh nhất (thời gian 10K tương đương tốt nhất)."""
    references = [(RACE_DISTANCES[label], effort["time_seconds"]) for label, effort in best_efforts.items() if label != "1K"]
    if profile and profile.recent_race:
        references.append((profile.recent_race.distance_meters, profile.recent_race.time_seconds))
    if not references:
        return None
    distance, seconds = min(references, key=lambda ref: riegel(ref[1], ref[0], 10000))
    return {label: round(riegel(seconds, distance, target)) for label, target in RACE_DISTANCES.items() if label != "1K"}


async def running_summary(session, user_id, options, profile: TrainingProfile | None) -> dict[str, Any]:
    manual, device = await _run_rows(session, user_id, options.start_date, options.end_date, options.timezone)
    rows = manual + device
    weeks: dict[date, dict] = {}
    current = week_start(options.start_date)
    while current <= options.end_date:
        weeks[current] = {"week_start": current, "runs": 0, "distance_meters": ZERO, "duration_seconds": ZERO, "longest_run_meters": ZERO}
        current += timedelta(days=7)
    by_type: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    easy = hard = unclassified = ZERO
    for row in rows:
        week = weeks[week_start(row.day)]
        week["runs"] += 1
        week["distance_meters"] += row.distance_meters or ZERO
        week["duration_seconds"] += row.duration_seconds or ZERO
        week["longest_run_meters"] = max(week["longest_run_meters"], row.distance_meters or ZERO)
        if is_device(row):  # chưa biết cường độ: không tính vào loại bài và tỉ lệ chạy nhẹ
            unclassified += row.duration_seconds or ZERO
            continue
        workout = row.performance.get("workout_type", WorkoutType.EASY.value)
        by_type[workout][0] += row.duration_seconds or ZERO
        by_type[workout][1] += row.distance_meters or ZERO
        if WorkoutType(workout) in HARD_WORKOUTS:
            hard += row.duration_seconds or ZERO
        else:
            easy += row.duration_seconds or ZERO
    efforts = _best_efforts(rows)
    sources = {"sources": {"manual_runs": len(manual), "device_runs": len(device),
                           "unclassified_seconds": float(unclassified)}} if device else {}
    return {
        **sources,
        "timezone": options.timezone, "start_date": options.start_date, "end_date": options.end_date,
        "weeks": [{**w, "pace_seconds_per_km": float(w["duration_seconds"] * 1000 / w["distance_meters"]) if w["distance_meters"] else None}
                  for w in weeks.values()],
        "pace_by_workout_type": {k: round(float(t * 1000 / d), 1) for k, (t, d) in by_type.items() if d},
        "easy_share_pct": round(float(easy * 100 / (easy + hard)), 1) if easy + hard else None,
        "best_efforts_seconds": efforts, "race_predictions_seconds": predictions(efforts, profile),
    }


async def recent_runs(session, user_id, start: date, end: date, zone: str, *, limit: int = 1) -> list[dict[str, Any]]:
    """Buổi chạy mới nhất trước: ngày, quãng đường, thời lượng, pace và loại bài (None với buổi từ thiết bị)."""
    manual, device = await _run_rows(session, user_id, start, end, zone)
    rows = sorted(manual + device, key=lambda r: (r.day, str(r.training_id)), reverse=True)
    return [{"date": r.day.isoformat(), "distance_km": round(float(r.distance_meters) / 1000, 2) if r.distance_meters else None,
             "duration_min": round(float(r.duration_seconds) / 60, 1) if r.duration_seconds else None,
             "pace_s_per_km": round(float(r.duration_seconds * 1000 / r.distance_meters)) if r.distance_meters and r.duration_seconds else None,
             "workout_type": None if is_device(r) else r.performance.get("workout_type", WorkoutType.EASY.value),
             **({"source": "device" if is_device(r) else "manual"} if device else {})} for r in rows[:limit]]


# ----------------------------------------------------------------- hồ sơ

def profile_read(personal_info: dict | None, measured_resting_hr: int | None = None) -> dict[str, Any]:
    """measured_resting_hr: trung vị 7 ngày của thiết bị, chỉ dùng khi chưa khai báo."""
    raw = (personal_info or {}).get("training")
    profile = TrainingProfile.model_validate(raw) if isinstance(raw, dict) else TrainingProfile()
    threshold, source = profile.threshold_pace_s_per_km, "PROFILE" if profile.threshold_pace_s_per_km else None
    if threshold is None and profile.recent_race:
        threshold, source = threshold_from_race(profile.recent_race.distance_meters, profile.recent_race.time_seconds), "RECENT_RACE"
    race = profile.recent_race
    resting = profile.resting_hr or measured_resting_hr
    return {
        "profile": profile, "configured": isinstance(raw, dict),
        "hr_zones": hr_zones(profile.max_hr, resting) if profile.max_hr else None,
        "resting_hr_source": "PROFILE" if profile.resting_hr else "DEVICE" if measured_resting_hr else None,
        "pace_zones": pace_zones(threshold) if threshold else None, "threshold_source": source,
        "race_predictions_seconds": {label: round(riegel(race.time_seconds, race.distance_meters, d))
                                     for label, d in RACE_DISTANCES.items() if label != "1K"} if race else None,
    }


# ----------------------------------------------------------------- insight

def _insight(code, severity, discipline, message, **evidence) -> dict[str, Any]:
    return {"code": code, "severity": severity, "discipline": discipline, "message_vi": message,
            "evidence": {k: (float(v) if isinstance(v, Decimal) else v) for k, v in evidence.items()}}


async def insights(session, user_id, options, *, profile: TrainingProfile, bodyweight_kg: float | None) -> dict[str, Any]:
    zone = options.timezone
    end = options.end_date or today_in(zone)
    found: list[dict[str, Any]] = []
    window = await _rows(session, user_id, end - timedelta(days=41), end, zone)
    sessions = _sessions(window)

    # Tải: ACWR tại ngày kết thúc.
    loads, missing = await daily_loads(session, user_id, end - timedelta(days=34), end, zone)
    acute, chronic, ratio = _acwr(loads, end)
    if ratio is not None and chronic > 0:
        if ratio > ACWR_DANGER:
            found.append(_insight("ACWR_SPIKE", "WARNING", "GENERAL", f"Tải 7 ngày gần nhất gấp {ratio} lần mức trung bình 4 tuần (>{ACWR_DANGER}): nguy cơ quá tải, nên giảm cường độ vài ngày.",
                                  acwr=ratio, acute_7d=acute, chronic_weekly=chronic, threshold=ACWR_DANGER))
        elif ratio > ACWR_HIGH:
            found.append(_insight("ACWR_HIGH", "NOTICE", "GENERAL", f"Tải tăng nhanh (ACWR {ratio}); duy trì, chưa nên tăng thêm.", acwr=ratio, threshold=ACWR_HIGH))
        elif ratio < ACWR_LOW:
            found.append(_insight("ACWR_LOW", "INFO", "GENERAL", f"Tải tuần này thấp hơn nền 4 tuần (ACWR {ratio}); phù hợp nếu đang giảm tải, nếu không có thể tăng dần.",
                                  acwr=ratio, threshold=ACWR_LOW))
    if missing:
        found.append(_insight("MISSING_RPE", "INFO", "GENERAL", f"{missing} buổi gần đây thiếu RPE buổi tập nên tải chưa đầy đủ.", sessions=missing))

    # Số ngày tập liên tiếp.
    trained_days = {row.day for row in sessions.values()}
    streak, day = 0, end
    while day in trained_days:
        streak += 1
        day -= timedelta(days=1)
    if streak >= MAX_CONSECUTIVE_DAYS:
        found.append(_insight("NO_REST_DAY", "WARNING", "GENERAL", f"Đã tập {streak} ngày liên tiếp; nên có ít nhất 1 ngày nghỉ.", days=streak))

    # Chạy bộ: bước nhảy quãng đường theo tuần và phân bố cường độ.
    this_week = [r for r in window if r.is_run and r.day > end - timedelta(days=7)]
    last_week = [r for r in window if r.is_run and end - timedelta(days=14) < r.day <= end - timedelta(days=7)]
    km_now = sum((r.distance_meters or ZERO for r in this_week), ZERO) / 1000
    km_before = sum((r.distance_meters or ZERO for r in last_week), ZERO) / 1000
    if km_before > 0 and km_now > 0:
        change = float((km_now - km_before) / km_before)
        if change > WEEKLY_RUN_WARNING:
            found.append(_insight("RUN_DISTANCE_SPIKE", "WARNING", "RUNNING", f"Km chạy 7 ngày tăng {change:.0%} so với tuần trước ({km_before:.1f}→{km_now:.1f} km); tăng >30% làm tăng nguy cơ chấn thương.",
                                  previous_km=round(km_before, 2), current_km=round(km_now, 2), change_pct=round(change * 100, 1)))
        elif change > WEEKLY_RUN_NOTICE:
            found.append(_insight("RUN_DISTANCE_INCREASE", "NOTICE", "RUNNING", f"Km chạy tăng {change:.0%} (>10%); giữ mức này thêm 1 tuần trước khi tăng tiếp.",
                                  previous_km=round(km_before, 2), current_km=round(km_now, 2), change_pct=round(change * 100, 1)))
    recent_runs = [r for r in window if r.is_run and r.day > end - timedelta(days=28)]
    if len(recent_runs) >= 3:
        hard = sum((r.duration_seconds or ZERO for r in recent_runs if WorkoutType(r.performance.get("workout_type", "EASY")) in HARD_WORKOUTS), ZERO)
        total = sum((r.duration_seconds or ZERO for r in recent_runs), ZERO)
        share = float((total - hard) * 100 / total) if total else None
        if share is not None and share < EASY_SHARE_MIN:
            found.append(_insight("TOO_MUCH_INTENSITY", "NOTICE", "RUNNING", f"Chỉ {share:.0f}% thời gian chạy 4 tuần là cường độ nhẹ (khuyến nghị ~80%); thêm buổi easy, bớt buổi nặng.",
                                  easy_share_pct=round(share, 1), target_pct=80, runs=len(recent_runs)))

    # Sức mạnh: số set nặng mỗi tuần theo nhóm cơ (7 ngày gần nhất).
    muscles: dict[str, int] = defaultdict(int)
    for row in window:
        if row.kind == "STRENGTH" and row.day > end - timedelta(days=7):
            for muscle in row.snapshot.get("muscle_groups") or []:
                muscles[muscle] += row.hard_sets or 0
    low = {m: n for m, n in muscles.items() if n < HARD_SETS_LOW}
    high = {m: n for m, n in muscles.items() if n > HARD_SETS_HIGH}
    if muscles and low and profile.primary_focus != "RUNNING":
        found.append(_insight("LOW_MUSCLE_VOLUME", "INFO", "STRENGTH", "Một số nhóm cơ dưới 10 hard sets/tuần, mức thường dùng để phát triển cơ: " + ", ".join(f"{m} {n}" for m, n in sorted(low.items())),
                              hard_sets=low, threshold=HARD_SETS_LOW))
    if high:
        found.append(_insight("HIGH_MUSCLE_VOLUME", "NOTICE", "STRENGTH", "Một số nhóm cơ vượt 20 hard sets/tuần, khó hồi phục: " + ", ".join(f"{m} {n}" for m, n in sorted(high.items())),
                              hard_sets=high, threshold=HARD_SETS_HIGH))

    # Sức mạnh: chững lại (không có e1RM tốt nhất mới trong 21 ngày gần nhất so với 21 ngày trước đó) và PR mới.
    by_exercise: dict[Any, list[Row]] = defaultdict(list)
    for row in window:
        if row.kind == "STRENGTH" and row.best_e1rm_kg is not None:
            by_exercise[row.exercise_id].append(row)
    for items in by_exercise.values():
        recent = [r.best_e1rm_kg for r in items if r.day > end - timedelta(days=21)]
        earlier = [r.best_e1rm_kg for r in items if r.day <= end - timedelta(days=21)]
        if len(recent) >= 3 and earlier and max(recent) <= max(earlier) * Decimal("1.005"):
            found.append(_insight("STRENGTH_PLATEAU", "NOTICE", "STRENGTH", f"{items[0].name}: e1RM không tăng sau ≥3 tuần ({max(earlier):.1f}→{max(recent):.1f} kg). Cân nhắc tuần giảm tải (deload) hoặc đổi rep range/biến thể.",
                                  exercise=items[0].name, previous_best_e1rm=max(earlier), recent_best_e1rm=max(recent), sessions=len(recent)))
    records = await strength_records(session, user_id, timezone=zone, until=end)
    # Lần ghi đầu tiên là mốc, không phải kỷ lục: cần có lịch sử trước đó.
    history = {row.exercise_id for row in window if row.kind == "STRENGTH" and row.day <= end - timedelta(days=7)}
    for record in records["records"]:
        if record["best_e1rm_date"] and record["best_e1rm_date"] > end - timedelta(days=7) and record["exercise_id"] in history:
            found.append(_insight("NEW_PR", "POSITIVE", "STRENGTH", f"Kỷ lục mới {record['exercise_name']}: e1RM {record['best_e1rm_kg']:.1f} kg.",
                                  exercise=record["exercise_name"], best_e1rm_kg=record["best_e1rm_kg"], date=record["best_e1rm_date"].isoformat()))

    # Mức tuân thủ kế hoạch trong 14 ngày gần nhất.
    planned, planned_ids = await _planned(session, user_id, end - timedelta(days=13), end)
    planned_total = sum(planned.values())
    if planned_total >= 3:
        recent_sessions = await _rows(session, user_id, end - timedelta(days=20), end, zone)
        done = {r.source_entry_id for r in recent_sessions if r.source_entry_id in planned_ids}
        adherence = 100 * len(done) / planned_total
        if adherence < ADHERENCE_MIN:
            found.append(_insight("LOW_ADHERENCE", "NOTICE", "GENERAL", f"Hoàn thành {len(done)}/{planned_total} buổi theo lịch 2 tuần qua ({adherence:.0f}%). Cân nhắc giảm số buổi/tuần cho vừa lịch.",
                                  planned=planned_total, completed=len(done), adherence_pct=round(adherence, 1)))

    # Cầu nối dinh dưỡng: hướng dẫn nạp năng lượng theo cân nặng cho 2 ngày gần nhất.
    recent_load = [row for row in sessions.values() if row.day >= end - timedelta(days=1)]
    if recent_load:
        long_session = max((float(r.session_seconds or 0) for r in recent_load), default=0)
        endurance_minutes = sum(float(r.duration_seconds or 0) for r in window if r.day >= end - timedelta(days=1) and r.kind == "ENDURANCE") / 60
        carbs = CARB_G_PER_KG_HIGH if long_session >= LONG_SESSION_SECONDS or endurance_minutes >= 90 else CARB_G_PER_KG_MODERATE
        evidence = {"carb_g_per_kg": list(carbs), "protein_g_per_kg": list(PROTEIN_G_PER_KG), "endurance_minutes_48h": round(endurance_minutes)}
        if bodyweight_kg:
            evidence |= {"bodyweight_kg": bodyweight_kg, "carb_g": [round(carbs[0] * bodyweight_kg), round(carbs[1] * bodyweight_kg)],
                         "protein_g": [round(PROTEIN_G_PER_KG[0] * bodyweight_kg), round(PROTEIN_G_PER_KG[1] * bodyweight_kg)]}
            message = (f"Gợi ý dinh dưỡng theo tải tập 48h: carb {evidence['carb_g'][0]}–{evidence['carb_g'][1]} g/ngày ({carbs[0]}–{carbs[1]} g/kg), "
                       f"protein {evidence['protein_g'][0]}–{evidence['protein_g'][1]} g/ngày, chia đều các bữa và có một bữa sau tập.")
        else:
            message = f"Gợi ý dinh dưỡng: carb {carbs[0]}–{carbs[1]} g/kg/ngày, protein {PROTEIN_G_PER_KG[0]}–{PROTEIN_G_PER_KG[1]} g/kg/ngày (cần cân nặng để tính gram)."
        found.append(_insight("FUELING", "INFO", "NUTRITION", message, **evidence))

    order = {"WARNING": 0, "NOTICE": 1, "POSITIVE": 2, "INFO": 3}
    found.sort(key=lambda item: order[item["severity"]])
    return {"end_date": end, "timezone": zone, "insights": found}


async def daily_training_load(session, user_id, options) -> dict[date, Decimal]:
    loads, _missing = await daily_loads(session, user_id, options.start_date, options.end_date, options.timezone)
    return loads
