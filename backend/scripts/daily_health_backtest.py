"""Backtest Daily Health: chạy engine readiness và bộ soạn thông báo trên kịch bản mô phỏng và dữ liệu thật.

    python -m scripts.daily_health_backtest --scenarios            # dữ liệu tổng hợp có nhãn (không cần DB)
    python -m scripts.daily_health_backtest --real --days 60       # dữ liệu thật, chỉ đọc (DB theo backend/.env)

Kịch bản là dữ liệu TỔNG HỢP: nhãn do chính bộ sinh đặt ra (ngày nào có quá tải, ốm, ngủ kém, thiếu dữ liệu),
nên đây là kiểm tra tính nhất quán và tần suất thông báo của heuristic, KHÔNG phải kiểm định lâm sàng.
Mỗi ngày được đánh giá như lúc 08:00 sáng hôm đó, với đồng bộ thành công một giờ trước.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from zoneinfo import ZoneInfo

from domains.analytics.services.daily_health import analytics
from domains.analytics.services.daily_health.service import WINDOW_DAYS, build
from domains.health_records import ports
from domains.notifications.schemas.notification import NotificationPreferences
from domains.notifications.services import briefing

ZONE = "Asia/Ho_Chi_Minh"
TZ = ZoneInfo(ZONE)
DAYS = 90
FIRST_EVALUATED = 35          # cần 28 ngày nền + 7 ngày xu hướng
END = date(2026, 11, 8)
COLUMNS = ("sleep_minutes", "hrv_ms", "resting_hr_bpm", "spo2_avg_pct", "respiratory_rate", "skin_temp_delta_c",
           "steps", "active_zone_minutes")
ALERT = {"ease_off", "recover", "needs_review"}
OUT = Path(__file__).resolve().parents[1] / "eval_results" / "daily_health"


@dataclass
class Day:
    values: dict[str, float | None]
    bedtime: float | None = 23.0          # giờ địa phương (24.5 = 00:30 hôm sau)
    sleep_hours: float | None = 7.5
    manual: bool = False
    load: float = 300.0
    label: str = "normal"                 # normal | strain | review | missing
    stages: bool = True


@dataclass
class Scenario:
    name: str
    description: str
    days: list[Day]
    expect: dict[str, str] = field(default_factory=dict)


def _normal_day(rng: random.Random) -> Day:
    hours = rng.gauss(7.5, 0.4)
    return Day(values={
        "hrv_ms": round(50 * math.exp(rng.gauss(0, 0.10)), 1), "resting_hr_bpm": round(rng.gauss(58, 1.5)),
        "spo2_avg_pct": round(rng.gauss(96, 0.5), 1), "respiratory_rate": round(rng.gauss(14, 0.4), 1),
        "skin_temp_delta_c": round(rng.gauss(0, 0.15), 2), "steps": round(rng.gauss(8000, 1500)),
        "active_zone_minutes": round(max(0, rng.gauss(30, 10)))},
        bedtime=rng.gauss(23.0, 0.35), sleep_hours=hours,
        load=max(0.0, rng.gauss(300, 80)) if rng.random() < 0.7 else 0.0)


def _base(seed: int) -> tuple[random.Random, list[Day]]:
    rng = random.Random(seed)
    return rng, [_normal_day(rng) for _ in range(DAYS)]


def _scenarios(seed: int) -> list[Scenario]:
    found = []
    _rng, days = _base(seed)
    found.append(Scenario("baseline_normal", "Không có sự kiện: đo tỉ lệ báo động nhầm của heuristic", days))

    _rng, days = _base(seed + 1)
    for index in range(60, 67):
        days[index].load *= 3.2
    for index in range(62, 67):
        days[index].values["resting_hr_bpm"] += 6
        days[index].values["hrv_ms"] = round(days[index].values["hrv_ms"] * 0.78, 1)
        days[index].label = "strain"
    found.append(Scenario("overreaching", "Tải tăng ×3 từ ngày 60; RHR +6, HRV −22% ngày 62–66", days))

    _rng, days = _base(seed + 2)
    for index in range(70, 73):
        values = days[index].values
        values["resting_hr_bpm"] += 9
        values["hrv_ms"] = round(values["hrv_ms"] * 0.65, 1)
        values["respiratory_rate"] = round(values["respiratory_rate"] + 2.0, 1)
        values["skin_temp_delta_c"] = round(values["skin_temp_delta_c"] + 1.3, 2)
        days[index].label = "review"
    found.append(Scenario("illness_onset", "Ngày 70–72: RHR +9, HRV −35%, nhịp thở +2, nhiệt độ da +1,3 °C", days))

    _rng, days = _base(seed + 3)
    for index in range(75, 82):
        days[index].sleep_hours, days[index].bedtime, days[index].label = 5.0, 25.5, "strain"
    found.append(Scenario("poor_sleep_week", "Ngày 75–81: ngủ 5 giờ, đi ngủ 01:30", days))

    rng, days = _base(seed + 4)
    for index in range(55, DAYS):
        days[index].bedtime = 21.5 if index % 2 else 25.5
    found.append(Scenario("irregular_sleep", "Từ ngày 55: giờ ngủ xen kẽ 21:30 / 01:30, thời lượng bình thường", days))

    _rng, days = _base(seed + 5)
    for offset, index in enumerate(range(55, DAYS)):
        gain = min(1.0, offset / 20)
        days[index].values["hrv_ms"] = round(days[index].values["hrv_ms"] * (1 + 0.18 * gain), 1)
        days[index].values["resting_hr_bpm"] -= round(2.5 * gain)
    found.append(Scenario("improving", "Từ ngày 55: HRV tăng dần 18%, RHR giảm 2–3 bpm", days))

    _rng, days = _base(seed + 6)
    for index in range(50, 56):
        days[index] = Day(values={column: None for column in COLUMNS}, bedtime=None, sleep_hours=None, load=0.0,
                          label="missing")
    found.append(Scenario("missing_data", "Ngày 50–55: không đeo thiết bị (không có giấc ngủ, HRV, RHR)", days))

    _rng, days = _base(seed + 7)
    for day in days:
        day.values = {column: (day.values[column] if column in ("steps",) else None) for column in COLUMNS}
        day.manual, day.stages = True, False
        day.bedtime = round(day.bedtime * 2) / 2
    found.append(Scenario("manual_sleep_only", "Không có đồng hồ đo HRV/RHR; người dùng ghi tay giờ ngủ mỗi đêm", days))

    _rng, days = _base(seed + 8)
    for index in range(DAYS - 10):
        days[index] = Day(values={column: None for column in COLUMNS}, bedtime=None, sleep_hours=None, load=0.0,
                          label="missing")
    for index in range(DAYS - 10, DAYS - 10 + 7):
        days[index].label = "missing"           # chưa đủ 7 ngày nền
    found.append(Scenario("new_user", "Chỉ có 10 ngày dữ liệu cuối", days))
    return found


def _rows(days: list[Day]) -> tuple[list[Any], list[Any], dict[date, Decimal]]:
    daily, sleep, loads = [], [], {}
    for index, day in enumerate(days):
        local = END - timedelta(days=DAYS - 1 - index)
        minutes = round(day.sleep_hours * 60) if day.sleep_hours is not None else None
        daily.append(SimpleNamespace(local_date=local, **{**{c: None for c in COLUMNS}, **day.values,
                                                          "sleep_minutes": minutes}))
        if day.load:
            loads[local] = Decimal(str(round(day.load)))
        if minutes is None or day.bedtime is None:
            continue
        start = datetime.combine(local - timedelta(days=1), datetime.min.time(), TZ) + timedelta(hours=day.bedtime)
        end = start + timedelta(minutes=minutes)
        staged = day.stages and not day.manual
        sleep.append(SimpleNamespace(
            local_date=local, start_at=start, end_at=end, is_nap=False, is_main=True, minutes_asleep=minutes,
            minutes_in_period=round(minutes / 0.92) if staged else minutes, minutes_to_fall_asleep=12 if staged else None,
            minutes_awake=round(minutes * 0.08) if staged else None,
            deep_minutes=round(minutes * 0.18) if staged else None, rem_minutes=round(minutes * 0.22) if staged else None,
            light_minutes=round(minutes * 0.60) if staged else None, efficiency_pct=92.0 if staged else None,
            data_source={"manual": True} if day.manual else {}))
    return daily, sleep, loads


def _availability(day: date) -> dict[str, Any]:
    return {spec.data_type: ports.TypeAvailability(granted=True, enabled=True, complete_through=day,
                                                   complete_from=day - timedelta(days=120))
            for spec in analytics.METRICS}


def evaluate(daily: list[Any], sleep: list[Any], loads: dict[date, Decimal], days: list[date], *,
             availability: Callable[[date], dict[str, Any]] = _availability, age: int | None = 30,
             zone: str = ZONE) -> list[Any]:
    tz = ZoneInfo(zone)
    results = []
    for day in days:
        now = datetime.combine(day, datetime.min.time(), tz).replace(hour=8).astimezone(timezone.utc)
        status = ports.ProviderStatus(provider="GOOGLE_HEALTH", status="ACTIVE", last_success_at=now - timedelta(hours=1))
        results.append(build(day=day, zone=zone, now=now, daily=[row for row in daily if row.local_date <= day],
                             availability=availability(day), status=status,
                             loads={d: v for d, v in loads.items() if d <= day}, missing_rpe=0, age=age,
                             sleep=[night for night in sleep if day - timedelta(days=6) <= night.local_date <= day]))
    return results


def simulate_notifications(assessments: list[Any], prefs: NotificationPreferences | None = None) -> dict[str, Any]:
    """Hai nhịp mỗi ngày (giờ briefing và 3 giờ sau), dedup và giới hạn mỗi ngày như hộp thư thật."""
    prefs = prefs or NotificationPreferences(enabled=True)
    sent, keys, per_kind, neutral_ok = [], set(), Counter(), True
    briefing_hour, briefing_minute = map(int, prefs.briefing_time.split(":"))
    for assessment in assessments:
        used = 0
        for hours in (0, 3.02):
            local_now = datetime.combine(assessment.date, datetime.min.time(), TZ).replace(
                hour=briefing_hour, minute=briefing_minute) + timedelta(hours=hours)
            if briefing.quiet(prefs, local_now):
                continue
            for draft in briefing.compose(assessment, prefs, local_now):
                if draft.dedup_key in keys or used >= prefs.max_per_day:
                    continue
                keys.add(draft.dedup_key)
                used += 1
                per_kind[draft.kind] += 1
                sent.append({"date": assessment.date.isoformat(), "kind": draft.kind, "code": draft.code})
                if assessment.state == "needs_review" and (draft.code != "BRIEFING_NEUTRAL" and draft.kind == "briefing"
                                                           or any(ch.isdigit() for ch in draft.body)):
                    neutral_ok = False
    weeks = max(1.0, len(assessments) / 7)
    return {"total": len(sent), "per_week": round(len(sent) / weeks, 2),
            "per_week_by_kind": {kind: round(count / weeks, 2) for kind, count in sorted(per_kind.items())},
            "needs_review_always_neutral": neutral_ok, "sent": sent}


def score(scenario: Scenario, results: list[Any]) -> dict[str, Any]:
    labels = {END - timedelta(days=DAYS - 1 - index): day.label for index, day in enumerate(scenario.days)}
    by_label: dict[str, list[str]] = defaultdict(list)
    for result in results:
        by_label[labels[result.date]].append(result.state)
    rate = lambda states, wanted: round(sum(state in wanted for state in states) / len(states), 3) if states else None  # noqa: E731
    codes = Counter(reason.code for result in results for reason in result.reasons)
    return {
        "days": len(results), "states": dict(Counter(result.state for result in results)),
        "confidence": dict(Counter(result.confidence for result in results)),
        "false_alarm_rate": rate(by_label.get("normal", []), ALERT),
        "strain_detection": rate(by_label.get("strain", []), ALERT),
        "review_detection": rate(by_label.get("review", []), {"needs_review", "recover"}),
        "review_as_needs_review": rate(by_label.get("review", []), {"needs_review"}),
        "missing_as_insufficient": rate(by_label.get("missing", []), {"insufficient_data"}),
        "normal_insufficient": rate(by_label.get("normal", []), {"insufficient_data"}),
        "reason_codes": dict(codes.most_common()),
    }


def run_scenarios(seed: int = 7) -> dict[str, Any]:
    report = {}
    for scenario in _scenarios(seed):
        daily, sleep, loads = _rows(scenario.days)
        days = [END - timedelta(days=DAYS - 1 - index) for index in range(FIRST_EVALUATED, DAYS)]
        results = evaluate(daily, sleep, loads, days)
        notifications = simulate_notifications(results)
        report[scenario.name] = {"description": scenario.description, **score(scenario, results),
                                 "notifications": {k: v for k, v in notifications.items() if k != "sent"}}
    return report


async def run_real(days: int) -> list[dict[str, Any]]:
    from sqlalchemy import text

    from core.database import get_db_session
    from domains.health_records import views
    from domains.identity.models.user import User
    from domains.training.services import training_analytics

    report = []
    async with get_db_session() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        users = (await session.execute(text(
            "SELECT user_id FROM health_connections WHERE status IN ('ACTIVE', 'NEEDS_REAUTH')"))).scalars().all()
        for index, user_id in enumerate(users):
            user = await session.get(User, user_id)
            zone = await ports.user_timezone(session, user_id)
            today = datetime.now(ZoneInfo(zone)).date()
            start = today - timedelta(days=days + WINDOW_DAYS)
            daily = await views.daily(session, user_id, start, today, zone)
            sleep = await views.sleep(session, user_id, start, today)
            loads, _missing = await training_analytics.daily_loads(session, user_id, start, today, zone)
            status = await ports.provider_status(session, user_id)
            available = await ports.availability(session, user_id)
            age = user.age if user.age is not None else ((status.provider_profile or {}).get("age") if status else None)
            evaluated = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
            results = evaluate(daily, sleep, loads, evaluated, availability=lambda _day: available, age=age, zone=zone)
            notifications = simulate_notifications(results)
            report.append({"user": f"user-{index + 1}", "timezone": zone, "days": days,
                           "nights_with_sleep": len({night.local_date for night in sleep if not night.is_nap}),
                           "states": dict(Counter(r.state for r in results)),
                           "confidence": dict(Counter(r.confidence for r in results)),
                           "reason_codes": dict(Counter(reason.code for r in results for reason in r.reasons).most_common()),
                           "notifications": {k: v for k, v in notifications.items() if k != "sent"}})
        await session.rollback()
    return report


def markdown(scenarios: dict[str, Any] | None, real: list[dict[str, Any]] | None) -> str:
    lines = [f"# Backtest Daily Health ({datetime.now().date().isoformat()})", ""]
    if scenarios:
        lines += ["## Kịch bản mô phỏng (dữ liệu tổng hợp, nhãn do bộ sinh đặt)", "",
                  "| Kịch bản | Ngày | Trạng thái | Báo nhầm (ngày bình thường) | Bắt ngày căng | Bắt ngày ốm (review/recover) "
                  "| Thiếu dữ liệu → insufficient | Thông báo/tuần | needs_review luôn trung tính |",
                  "|---|---|---|---|---|---|---|---|---|"]
        fmt = lambda value: "—" if value is None else f"{100 * value:.0f}%"  # noqa: E731
        for name, row in scenarios.items():
            states = ", ".join(f"{state} {count}" for state, count in sorted(row["states"].items()))
            lines.append(f"| {name} | {row['days']} | {states} | {fmt(row['false_alarm_rate'])} | "
                         f"{fmt(row['strain_detection'])} | {fmt(row['review_detection'])} | "
                         f"{fmt(row['missing_as_insufficient'])} | {row['notifications']['per_week']} | "
                         f"{'có' if row['notifications']['needs_review_always_neutral'] else 'KHÔNG'} |")
        lines.append("")
    if real is not None:
        lines += ["## Dữ liệu thật (chỉ đọc)", ""]
        for row in real:
            lines.append(f"- {row['user']} ({row['timezone']}, {row['days']} ngày, {row['nights_with_sleep']} đêm có giấc ngủ): "
                         f"trạng thái {row['states']}, độ tin cậy {row['confidence']}, "
                         f"thông báo {row['notifications']['per_week']}/tuần {row['notifications']['per_week_by_kind']}")
        if not real:
            lines.append("- Không có người dùng nào có kết nối Google Health.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenarios", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    if not (args.scenarios or args.real):
        args.scenarios = True
    scenarios = run_scenarios(args.seed) if args.scenarios else None
    real = asyncio.run(run_real(args.days)) if args.real else None
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().date().isoformat()
    (OUT / f"backtest-{stamp}.json").write_text(json.dumps({"scenarios": scenarios, "real": real}, ensure_ascii=False,
                                                           indent=1, default=str))
    text = markdown(scenarios, real)
    (OUT / f"backtest-{stamp}.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
