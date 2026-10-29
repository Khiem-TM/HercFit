"""Static workout and program library; generates schedule previews, never writes.

Programs reference catalog exercises by system code. The preview is a complete
TrainingPlanCreate payload that the client (or agent) submits through the
normal confirmed create endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from fastapi import HTTPException

from schemas.exercises import ExerciseKind

DAY = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


# ----------------------------------------------------------------- builders

def sets(count: int, reps_min: int, reps_max: int | None = None, *, rpe: float | None = None,
         pct: float | None = None, rest: int | None = None, hold: int | None = None) -> dict[str, Any]:
    target: dict[str, Any] = {"count": count, "set_type": "WORKING"}
    if hold:
        target["hold_seconds"] = hold
    else:
        target["reps_min"] = reps_min
        if reps_max and reps_max != reps_min:
            target["reps_max"] = reps_max
    if pct:
        target["load"] = {"mode": "PCT_1RM", "value": pct}
    if rpe is not None:
        target["rpe_target"] = rpe
    if rest:
        target["rest_seconds"] = rest
    return target


def lift(code: str, *targets: dict[str, Any], rule: str = "DOUBLE_PROGRESSION", increment: float | None = 2.5) -> tuple[str, dict]:
    progression = {"rule": rule} | ({"increment_kg": increment} if increment and rule != "NONE" else {})
    return code, {"kind": ExerciseKind.STRENGTH.value, "sets": list(targets), "progression": progression}


def step(step_type: str = "WORK", *, minutes: float | None = None, meters: float | None = None,
         zone: str | None = None, rpe: tuple[float, float] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"step_type": step_type}
    if minutes is not None:
        result["duration_seconds"] = minutes * 60
    else:
        result["distance_meters"] = meters
    if zone:
        result["target"] = {"type": "PACE_ZONE", "zone": zone}
    elif rpe:
        result["target"] = {"type": "RPE", "low": rpe[0], "high": rpe[1]}
    return result


def repeat(times: int, *steps: dict[str, Any]) -> dict[str, Any]:
    return {"repeat": times, "steps": list(steps)}


def run(code: str, workout_type: str, *steps: dict[str, Any]) -> tuple[str, dict]:
    return code, {"kind": ExerciseKind.ENDURANCE.value, "workout_type": workout_type, "steps": list(steps)}


def warm(minutes: float = 10) -> dict[str, Any]:
    return step("WARMUP", minutes=minutes, zone="E")


def cool(minutes: float = 10) -> dict[str, Any]:
    return step("COOLDOWN", minutes=minutes, zone="E")


# ----------------------------------------------------------------- running workouts

RUN_WORKOUTS: dict[str, dict[str, Any]] = {
    "easy_run": {"name_vi": "Chạy nhẹ (Easy)", "level": "BEGINNER", "description_vi": "Chạy thoải mái vùng E, nói chuyện được; nền tảng sức bền hiếu khí.",
                 "build": lambda minutes=40: run("run_road", "EASY", step(minutes=minutes, zone="E"))},
    "recovery_run": {"name_vi": "Chạy hồi phục", "level": "BEGINNER", "description_vi": "Chạy rất nhẹ 20–30 phút sau buổi nặng.",
                     "build": lambda minutes=25: run("run_road", "RECOVERY", step(minutes=minutes, rpe=(2, 3)))},
    "long_run": {"name_vi": "Chạy dài (Long run)", "level": "BEGINNER", "description_vi": "Buổi dài nhất tuần ở vùng E, xây sức bền.",
                 "build": lambda km=10: run("run_road", "LONG", step(meters=km * 1000, zone="E"))},
    "tempo_run": {"name_vi": "Chạy tempo", "level": "INTERMEDIATE", "description_vi": "20 phút liên tục ở pace ngưỡng (T).",
                  "build": lambda minutes=20: run("run_road", "TEMPO", warm(), step(minutes=minutes, zone="T"), cool())},
    "cruise_intervals": {"name_vi": "Cruise intervals (ngưỡng)", "level": "INTERMEDIATE", "description_vi": "4×1600m pace T, nghỉ chạy nhẹ 1 phút.",
                         "build": lambda reps=4: run("run_road", "THRESHOLD", warm(), repeat(reps, step(meters=1600, zone="T"), step("RECOVERY", minutes=1, zone="E")), cool())},
    "vo2max_1000": {"name_vi": "Interval VO₂max 1000m", "level": "INTERMEDIATE", "description_vi": "5×1000m pace I, hồi phục chạy nhẹ 3 phút.",
                    "build": lambda reps=5: run("run_track", "INTERVAL", warm(15), repeat(reps, step(meters=1000, zone="I"), step("RECOVERY", minutes=3, zone="E")), cool())},
    "repeats_400": {"name_vi": "Lặp 400m (tốc độ)", "level": "INTERMEDIATE", "description_vi": "8×400m pace R, đi bộ/chạy nhẹ 400m.",
                    "build": lambda reps=8: run("run_track", "INTERVAL", warm(15), repeat(reps, step(meters=400, zone="R"), step("RECOVERY", meters=400, zone="E")), cool())},
    "fartlek": {"name_vi": "Fartlek", "level": "BEGINNER", "description_vi": "Chạy biến tốc: 8×(1 phút nhanh, 2 phút nhẹ).",
                "build": lambda reps=8: run("run_road", "FARTLEK", warm(), repeat(reps, step(minutes=1, rpe=(7, 8)), step("RECOVERY", minutes=2, zone="E")), cool())},
    "hill_repeats": {"name_vi": "Chạy dốc lặp", "level": "INTERMEDIATE", "description_vi": "8×60 giây lên dốc mạnh, đi/chạy xuống hồi phục.",
                     "build": lambda reps=8: run("run_road", "HILL", warm(15), repeat(reps, step(minutes=1, rpe=(8, 9)), step("RECOVERY", minutes=2, rpe=(2, 3))), cool())},
    "progression_run": {"name_vi": "Chạy tăng tốc dần", "level": "INTERMEDIATE", "description_vi": "Bắt đầu E, kết thúc ở M rồi T.",
                        "build": lambda: run("run_road", "PROGRESSION", step(minutes=20, zone="E"), step(minutes=15, zone="M"), step(minutes=5, zone="T"))},
    "strides": {"name_vi": "Chạy nhẹ + strides", "level": "BEGINNER", "description_vi": "Chạy nhẹ rồi 6×20 giây tăng tốc thả lỏng.",
                "build": lambda minutes=30: run("run_road", "EASY", step(minutes=minutes, zone="E"), repeat(6, step(minutes=1 / 3, rpe=(7, 8)), step("RECOVERY", minutes=1, rpe=(1, 2))))},
    "walk_run": {"name_vi": "Chạy xen đi bộ", "level": "BEGINNER", "description_vi": "Luân phiên chạy và đi bộ cho người mới.",
                 "build": lambda run_min=1, walk_min=2, reps=8: run("walk_run", "WALK_RUN", step("WARMUP", minutes=5, rpe=(2, 3)), repeat(reps, step(minutes=run_min, rpe=(5, 6)), step("RECOVERY", minutes=walk_min, rpe=(2, 3))), step("COOLDOWN", minutes=5, rpe=(2, 3)))},
    "time_trial_5k": {"name_vi": "Chạy thử 5K", "level": "BEGINNER", "description_vi": "5K tối đa sức để cập nhật vùng pace.",
                      "build": lambda: run("run_road", "RACE", warm(15), step(meters=5000, rpe=(9, 10)), cool())},
}


# ----------------------------------------------------------------- gym sessions

FULL_A = [lift("bb_back_squat", sets(3, 5, 8, rpe=7.5, rest=180)), lift("bb_bench_press", sets(3, 6, 10, rpe=7.5, rest=150)),
          lift("bb_bent_over_row", sets(3, 8, 12, rpe=7.5, rest=120)), lift("romanian_deadlift", sets(2, 8, 10, rpe=7, rest=120)),
          lift("plank", sets(3, 0, hold=40, rest=60), rule="NONE")]
FULL_B = [lift("bb_deadlift", sets(3, 3, 5, rpe=7.5, rest=180), increment=5), lift("bb_overhead_press", sets(3, 6, 10, rpe=7.5, rest=150)),
          lift("lat_pulldown", sets(3, 8, 12, rpe=8, rest=90)), lift("bulgarian_split_squat", sets(2, 8, 12, rpe=7.5, rest=90)),
          lift("hanging_leg_raise", sets(3, 8, 12, rest=60), rule="NONE")]
UPPER_A = [lift("bb_bench_press", sets(4, 5, 8, rpe=8, rest=180)), lift("bb_bent_over_row", sets(4, 6, 10, rpe=8, rest=150)),
           lift("db_shoulder_press", sets(3, 8, 12, rpe=8, rest=120)), lift("lat_pulldown", sets(3, 8, 12, rpe=8, rest=90)),
           lift("db_curl", sets(2, 10, 15, rpe=8, rest=60), increment=1), lift("triceps_pushdown", sets(2, 10, 15, rpe=8, rest=60), increment=2.5)]
LOWER_A = [lift("bb_back_squat", sets(4, 5, 8, rpe=8, rest=180)), lift("romanian_deadlift", sets(3, 8, 10, rpe=8, rest=150)),
           lift("leg_press", sets(3, 10, 15, rpe=8, rest=120), increment=5), lift("lying_leg_curl", sets(3, 10, 15, rpe=8, rest=90)),
           lift("standing_calf_raise", sets(3, 10, 15, rpe=8, rest=60))]
UPPER_B = [lift("bb_overhead_press", sets(4, 5, 8, rpe=8, rest=180)), lift("pull_up", sets(4, 6, 10, rpe=8, rest=150), rule="DOUBLE_PROGRESSION", increment=None),
           lift("db_incline_press", sets(3, 8, 12, rpe=8, rest=120)), lift("seated_cable_row", sets(3, 10, 12, rpe=8, rest=90)),
           lift("db_lateral_raise", sets(3, 12, 20, rpe=8, rest=60), increment=1), lift("hammer_curl", sets(2, 10, 15, rpe=8, rest=60), increment=1)]
LOWER_B = [lift("bb_deadlift", sets(4, 3, 5, rpe=8, rest=180), increment=5), lift("bb_front_squat", sets(3, 6, 10, rpe=8, rest=150)),
           lift("hip_thrust", sets(3, 8, 12, rpe=8, rest=120), increment=5), lift("walking_lunge", sets(2, 10, 12, rpe=8, rest=90)),
           lift("plank", sets(3, 0, hold=45, rest=60), rule="NONE")]
PUSH = [lift("bb_bench_press", sets(4, 5, 8, rpe=8, rest=180)), lift("bb_overhead_press", sets(3, 6, 10, rpe=8, rest=150)),
        lift("db_incline_press", sets(3, 8, 12, rpe=8, rest=120)), lift("db_lateral_raise", sets(3, 12, 20, rpe=8, rest=60), increment=1),
        lift("triceps_pushdown", sets(3, 10, 15, rpe=8, rest=60))]
PULL = [lift("bb_deadlift", sets(3, 3, 5, rpe=8, rest=180), increment=5), lift("pull_up", sets(3, 6, 10, rpe=8, rest=150), increment=None),
        lift("seated_cable_row", sets(3, 8, 12, rpe=8, rest=120)), lift("face_pull", sets(3, 12, 20, rpe=8, rest=60)),
        lift("db_curl", sets(3, 10, 15, rpe=8, rest=60), increment=1)]
LEGS = [lift("bb_back_squat", sets(4, 5, 8, rpe=8, rest=180)), lift("romanian_deadlift", sets(3, 8, 10, rpe=8, rest=150)),
        lift("leg_press", sets(3, 10, 15, rpe=8, rest=120), increment=5), lift("seated_leg_curl", sets(3, 10, 15, rpe=8, rest=90)),
        lift("standing_calf_raise", sets(4, 10, 15, rpe=8, rest=60))]


# ----------------------------------------------------------------- programs

@dataclass(frozen=True)
class Program:
    code: str
    name_vi: str
    description_vi: str
    discipline: str
    level: str
    weeks: int
    # week index (0-based) -> list of (weekday, label, items)
    week: Callable[[int, int], list[tuple[str, str, list[tuple[str, dict]]]]]
    sessions_per_week: int = field(default=0)


def _cutback(week: int) -> bool:
    """Every 4th week is a recovery week (reduced volume)."""
    return week % 4 == 3


def _long_km(week: int, start: float, cap: float) -> float:
    progress = start * (1.1 ** (week - week // 4))
    return round(min(progress * (0.8 if _cutback(week) else 1), cap), 1)


def _beginner_5k(week: int, total: int):
    # Run/walk ratio progresses towards 30 min continuous running.
    ladder = [(1, 2, 8), (2, 2, 6), (3, 2, 5), (5, 2, 4), (8, 2, 3), (10, 1, 3), (15, 1, 2), (30, 0, 1)]
    run_min, walk_min, reps = ladder[min(week, len(ladder) - 1)]
    workout = RUN_WORKOUTS["easy_run"]["build"](30) if walk_min == 0 else RUN_WORKOUTS["walk_run"]["build"](run_min, walk_min, reps)
    label = "Chạy 30 phút liên tục" if walk_min == 0 else f"Chạy {run_min}′ / đi {walk_min}′ × {reps}"
    if week == total - 1:
        return [("TUE", label, [workout]), ("THU", label, [workout]), ("SAT", "Chạy thử 5K", [RUN_WORKOUTS["time_trial_5k"]["build"]()])]
    return [(day, label, [workout]) for day in ("TUE", "THU", "SAT")]


def _base_10k(week: int, total: int):
    quality = RUN_WORKOUTS["tempo_run"]["build"](15 + 5 * min(week // 2, 3)) if week % 2 == 0 else RUN_WORKOUTS["cruise_intervals"]["build"](3 + min(week // 3, 2))
    if _cutback(week):
        quality = RUN_WORKOUTS["strides"]["build"](30)
    return [("TUE", "Chạy nhẹ", [RUN_WORKOUTS["easy_run"]["build"](35)]),
            ("THU", "Buổi chất lượng", [quality]),
            ("SAT", "Chạy hồi phục", [RUN_WORKOUTS["recovery_run"]["build"]()]),
            ("SUN", "Chạy dài", [RUN_WORKOUTS["long_run"]["build"](_long_km(week, 8, 16))])]


def _hybrid(week: int, total: int):
    return [("MON", "Gym toàn thân A", FULL_A), ("TUE", "Chạy nhẹ", [RUN_WORKOUTS["easy_run"]["build"](35)]),
            ("THU", "Gym toàn thân B", FULL_B),
            ("FRI", "Interval", [RUN_WORKOUTS["fartlek"]["build"]() if week % 2 == 0 else RUN_WORKOUTS["vo2max_1000"]["build"](4)]),
            ("SUN", "Chạy dài", [RUN_WORKOUTS["long_run"]["build"](_long_km(week, 7, 14))])]


PROGRAMS: dict[str, Program] = {p.code: p for p in (
    Program("gym_full_body_3x", "Gym toàn thân 3 buổi/tuần", "Hai buổi A/B luân phiên, ưu tiên bài compound, double progression.",
            "STRENGTH", "BEGINNER", 8, lambda w, t: [("MON", "Toàn thân A" if w % 2 == 0 else "Toàn thân B", FULL_A if w % 2 == 0 else FULL_B),
                                                    ("WED", "Toàn thân B" if w % 2 == 0 else "Toàn thân A", FULL_B if w % 2 == 0 else FULL_A),
                                                    ("FRI", "Toàn thân A" if w % 2 == 0 else "Toàn thân B", FULL_A if w % 2 == 0 else FULL_B)], 3),
    Program("gym_upper_lower_4x", "Gym Upper/Lower 4 buổi/tuần", "Thân trên/thân dưới, mỗi nhóm cơ 2 lần/tuần, ~10–16 hard sets/nhóm cơ.",
            "STRENGTH", "INTERMEDIATE", 8, lambda w, t: [("MON", "Thân trên A", UPPER_A), ("TUE", "Thân dưới A", LOWER_A),
                                                        ("THU", "Thân trên B", UPPER_B), ("FRI", "Thân dưới B", LOWER_B)], 4),
    Program("gym_ppl_6x", "Gym Push/Pull/Legs 6 buổi/tuần", "Đẩy/Kéo/Chân lặp 2 lần mỗi tuần cho người đã có nền tảng.",
            "STRENGTH", "ADVANCED", 8, lambda w, t: [(d, label, items) for d, (label, items) in zip(
                ("MON", "TUE", "WED", "THU", "FRI", "SAT"), [("Push", PUSH), ("Pull", PULL), ("Legs", LEGS)] * 2)], 6),
    Program("run_5k_beginner", "Chạy 5K cho người mới (8 tuần)", "Từ chạy xen đi bộ đến chạy liên tục 30 phút, tuần cuối chạy thử 5K.",
            "RUNNING", "BEGINNER", 8, _beginner_5k, 3),
    Program("run_10k_base", "Nền tảng 10K (8 tuần)", "4 buổi/tuần: nhẹ, chất lượng, hồi phục, chạy dài tăng ~10%/tuần; tuần 4 và 8 giảm tải.",
            "RUNNING", "INTERMEDIATE", 8, _base_10k, 4),
    Program("hybrid_2gym_3run", "Hybrid: 2 Gym + 3 Chạy", "Kết hợp sức mạnh toàn thân và chạy bộ; buổi chạy nặng tách xa buổi chân.",
            "HYBRID", "INTERMEDIATE", 8, _hybrid, 5),
)}


def list_templates() -> list[dict[str, Any]]:
    programs = [{"code": p.code, "kind": "PROGRAM", "discipline": p.discipline, "name_vi": p.name_vi, "description_vi": p.description_vi,
                 "level": p.level, "weeks": p.weeks, "sessions_per_week": p.sessions_per_week} for p in PROGRAMS.values()]
    workouts = [{"code": code, "kind": "WORKOUT", "discipline": "RUNNING", "name_vi": w["name_vi"], "description_vi": w["description_vi"],
                 "level": w["level"], "weeks": None, "sessions_per_week": None} for code, w in RUN_WORKOUTS.items()]
    return programs + workouts


async def build_schedule(session, *, user_id, code: str, start_date: date, weeks: int | None, name: str | None) -> dict[str, Any]:
    """Return a TrainingPlanCreate payload; exercise codes resolve to visible SYSTEM ids."""
    from models.exercises import Exercise

    program = PROGRAMS.get(code)
    if program is None:
        raise HTTPException(404, "Program template not found")
    total = weeks or program.weeks
    monday = start_date - timedelta(days=start_date.weekday())
    ids: dict[tuple[str, str], Any] = {}
    entries = []
    for week in range(total):
        for weekday, label, items in program.week(week, total):
            day = monday + timedelta(weeks=week, days=DAY[weekday])
            if day < start_date:
                continue
            resolved = []
            for exercise_code, prescription in items:
                key = (prescription["kind"], exercise_code)
                if key not in ids:
                    exercise = await Exercise.get_system_by_code(session, exercise_code, kind=prescription["kind"])
                    if exercise is None:
                        raise HTTPException(409, f"System exercise '{exercise_code}' is missing; seed the training catalog")
                    ids[key] = str(exercise.id)
                resolved.append({"exercise_id": ids[key], "prescription": prescription})
            entries.append({"scheduled_date": day.isoformat(), "label": label + (" (giảm tải)" if _cutback(week) and program.discipline != "STRENGTH" else ""),
                            "is_rest": False, "items": resolved})
    if not entries:
        raise HTTPException(422, "No sessions fall within the requested period")
    end = max(date.fromisoformat(entry["scheduled_date"]) for entry in entries)
    return {"name": name or program.name_vi, "start_date": start_date.isoformat(), "end_date": end.isoformat(),
            "note": f"Tạo từ mẫu {program.code}", "entries": entries}
