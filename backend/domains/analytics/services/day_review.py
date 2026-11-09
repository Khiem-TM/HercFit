"""Đánh giá chất lượng một ngày: hàm thuần, tất định, có phiên bản. LLM chỉ diễn giải kết quả này.

Mỗi mặt được chấm 0–100 khi có dữ liệu, ngược lại là `missing` và không tính vào điểm tổng (không bao giờ
coi dữ liệu thiếu là ngày tệ). Điểm tổng là trung bình có trọng số trên các mặt có dữ liệu, cần ít nhất 2 mặt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from domains.analytics.services.health_rules import catalog
from domains.analytics.services.health_rules.evaluate import Features, Profile, hm, vn

ALGORITHM_VERSION = "day-review-v1"
Rating = Literal["good", "fair", "poor", "missing"]
WEIGHTS = {"nutrition": 0.30, "activity": 0.25, "sleep": 0.25, "recovery": 0.10, "plan": 0.10}
LABELS = {"nutrition": "Dinh dưỡng", "activity": "Vận động", "sleep": "Giấc ngủ", "recovery": "Hồi phục",
          "plan": "Lịch tập"}
MIN_DIMENSIONS = 2
STEPS_TARGET = 7000
GRADES = ((85, "Rất tốt"), (70, "Tốt"), (50, "Trung bình"), (0, "Cần cải thiện"))
TIPS = {
    "nutrition": "Ngày mai ghi đủ các bữa và bám sát mục tiêu năng lượng, ưu tiên đạm trong mỗi bữa.",
    "activity": "Ngày mai thêm 20–30 phút đi bộ nhanh hoặc một buổi tập ngắn.",
    "sleep": "Tối nay đi ngủ sớm hơn 30 phút để bù giấc.",
    "recovery": "Ngày mai ưu tiên vận động nhẹ và nghỉ ngơi để cơ thể hồi phục.",
    "plan": "Sắp xếp lại buổi tập bị lỡ vào ngày trống gần nhất.",
}
METHOD = {
    "nutrition": "Năng lượng ăn vào so với mục tiêu (±10% = 100, ±20% = 75, ±30% = 50, còn lại 25) × 0,6 + đạm so "
                 "với mục tiêu (≥ 90% = 100, ≥ 75% = 75, ≥ 50% = 50, còn lại 25) × 0,4; cần ít nhất 2 bữa đã ghi",
    "activity": "Lấy mức cao hơn giữa phút vùng tim so với 150 phút/tuần chia 7 (BYT 2892, WHO 2020; trẻ dưới 18 tuổi "
                "60 phút/ngày) và bước chân so với 7.000 bước (Ding và cs., Lancet Public Health 2025)",
    "sleep": "Đêm qua trong khoảng khuyến nghị theo tuổi = 100; thiếu ≤ 1 giờ hoặc dư > 1 giờ = 70; thiếu 1–2 giờ = 45; "
             "thiếu hơn 2 giờ = 20 (NSF 2015)",
    "recovery": "Điểm sẵn sàng của ngày (readiness v3)",
    "plan": "Có buổi tập trong lịch: đã ghi nhận = 100, chưa = 0; ngày nghỉ không tính",
    "overall": "Trung bình có trọng số (dinh dưỡng 0,30; vận động 0,25; giấc ngủ 0,25; hồi phục 0,10; lịch tập 0,10) "
               "trên các mặt có dữ liệu; xếp loại Rất tốt ≥ 85, Tốt ≥ 70, Trung bình ≥ 50",
}


@dataclass(frozen=True)
class Dimension:
    id: str
    score: int | None
    detail: str
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def rating(self) -> Rating:
        if self.score is None:
            return "missing"
        return "good" if self.score >= 80 else "fair" if self.score >= 55 else "poor"

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": LABELS[self.id], "score": self.score, "rating": self.rating,
                "detail": self.detail, "values": self.values}


@dataclass(frozen=True)
class DayReview:
    date: date
    dimensions: list[Dimension]
    score: int | None
    grade: str | None

    @property
    def enough(self) -> bool:
        return self.score is not None

    def weakest(self) -> Dimension | None:
        scored = [d for d in self.dimensions if d.score is not None]
        return min(scored, key=lambda d: d.score) if scored else None

    def as_dict(self) -> dict[str, Any]:
        return {"date": self.date.isoformat(), "score": self.score, "grade": self.grade,
                "algorithm_version": ALGORITHM_VERSION, "dimensions": [d.as_dict() for d in self.dimensions]}


def _band(ratio: float, steps: tuple[tuple[float, int], ...], last: int) -> int:
    return next((score for limit, score in steps if ratio <= limit), last)


def nutrition(features: Features, profile: Profile) -> Dimension:
    row = features.intake.get(features.today)
    if row is None or row.meals < 2 or row.kcal is None or not profile.target_kcal:
        return Dimension("nutrition", None, "Chưa ghi đủ bữa hôm nay.")
    energy = _band(abs(row.kcal / profile.target_kcal - 1), ((0.10, 100), (0.20, 75), (0.30, 50)), 25)
    parts = [f"ăn {vn(row.kcal)}/{vn(profile.target_kcal)} kcal"]
    values: dict[str, Any] = {"meals": row.meals, "kcal": round(row.kcal), "target_kcal": round(profile.target_kcal)}
    score = energy
    if row.protein_g is not None and profile.protein_target_g:
        ratio = row.protein_g / profile.protein_target_g
        protein = 100 if ratio >= 0.9 else 75 if ratio >= 0.75 else 50 if ratio >= 0.5 else 25
        score = round(0.6 * energy + 0.4 * protein)
        parts.append(f"đạm {vn(row.protein_g)}/{vn(profile.protein_target_g)} g")
        values.update(protein_g=round(row.protein_g), protein_target_g=round(profile.protein_target_g))
    return Dimension("nutrition", score, ", ".join(parts).capitalize() + f" ({row.meals} bữa).", values)


def activity(features: Features, profile: Profile) -> Dimension:
    row = features.health.get(features.today)
    azm = row.active_zone_minutes if row is not None else None
    steps = row.steps if row is not None else None
    if azm is None and steps is None:
        return Dimension("activity", None, "Chưa có dữ liệu vận động hôm nay.")
    daily = 60 if profile.minor else catalog.ACTIVITY_MIN_PER_WEEK / 7
    scores, parts, values = [], [], {}
    if azm is not None:
        scores.append(min(100, round(azm / daily * 100)))
        parts.append(f"{vn(azm)} phút vận động vừa–mạnh (mục tiêu khoảng {vn(daily)} phút/ngày)")
        values.update(active_zone_minutes=azm, target_minutes=round(daily))
    if steps is not None:
        scores.append(min(100, round(steps / STEPS_TARGET * 100)))
        parts.append(f"{vn(steps)} bước")
        values.update(steps=steps, steps_target=STEPS_TARGET)
    return Dimension("activity", max(scores), ", ".join(parts).capitalize() + ".", values)


def sleep(features: Features, profile: Profile) -> Dimension:
    row = features.health.get(features.today)
    minutes = row.sleep_minutes if row is not None else None
    if minutes is None:
        return Dimension("sleep", None, "Chưa có dữ liệu giấc ngủ đêm qua.")
    low, high = profile.recommended_sleep
    short = low * 60 - minutes
    if short <= 0:
        score = 100 if minutes <= high * 60 + 60 else 70
    else:
        score = 70 if short <= 60 else 45 if short <= 120 else 20
    return Dimension("sleep", score, f"Đêm qua ngủ {hm(minutes)} (khuyến nghị {vn(low)}–{vn(high)} giờ).",
                     {"minutes": minutes, "recommended_hours": [low, high]})


def recovery(readiness_score: int | None) -> Dimension:
    if readiness_score is None:
        return Dimension("recovery", None, "Chưa có điểm sẵn sàng hôm nay.")
    return Dimension("recovery", int(readiness_score), f"Điểm sẵn sàng {readiness_score}/100.",
                     {"readiness_score": readiness_score})


def plan(sessions: list[tuple[str, bool]]) -> Dimension:
    if not sessions:
        return Dimension("plan", None, "Hôm nay là ngày nghỉ hoặc chưa có lịch tập.")
    done = [label for label, completed in sessions if completed]
    if done:
        return Dimension("plan", 100, f"Đã hoàn thành buổi {', '.join(done)}.", {"done": done})
    labels = [label for label, _ in sessions]
    return Dimension("plan", 0, f"Chưa ghi nhận buổi {', '.join(labels)} trong lịch.", {"pending": labels})


def review(features: Features, profile: Profile, *, readiness_score: int | None,
           sessions: list[tuple[str, bool]]) -> DayReview:
    """sessions: các buổi (không phải ngày nghỉ) trong lịch hôm nay, kèm đã ghi nhận hay chưa."""
    dimensions = [nutrition(features, profile), activity(features, profile), sleep(features, profile),
                  recovery(readiness_score), plan(sessions)]
    scored = [d for d in dimensions if d.score is not None]
    if len(scored) < MIN_DIMENSIONS:
        return DayReview(features.today, dimensions, None, None)
    total = sum(WEIGHTS[d.id] for d in scored)
    score = round(sum(WEIGHTS[d.id] * d.score for d in scored) / total)
    grade = next(label for limit, label in GRADES if score >= limit)
    return DayReview(features.today, dimensions, score, grade)
