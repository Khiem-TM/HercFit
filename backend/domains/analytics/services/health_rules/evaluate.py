"""Hàm thuần của bộ luật: Features + Profile → Signal. Không I/O, không LLM.

Thiếu dữ liệu thì luật im lặng (không bao giờ coi giá trị thiếu là 0). Mỗi Signal mang câu chữ do code viết
(`title`, `fact`, `advice`) để dùng khi không có LLM, và đủ feature để LLM viết lại mà không phải tính gì.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Iterable

from domains.analytics.services.health_rules import catalog as c


@dataclass(frozen=True)
class Profile:
    sex: str | None = None
    age: int | None = None
    height_cm: float | None = None
    goal: str | None = None
    # Người tập luyện thường xuyên: kinh nghiệm từ trung bình trở lên hoặc mức vận động active/very_active.
    trained: bool = False
    bmr_kcal: float | None = None
    target_kcal: float | None = None
    protein_target_g: float | None = None
    recommended_sleep: tuple[float, float] = (7.0, 9.0)

    @property
    def minor(self) -> bool:
        return self.age is not None and self.age < 18


@dataclass(frozen=True)
class DayHealth:
    rhr: float | None = None
    spo2: float | None = None
    sleep_minutes: int | None = None
    steps: int | None = None
    active_zone_minutes: int | None = None
    energy_out: float | None = None


@dataclass(frozen=True)
class DayIntake:
    meals: int = 0
    complete: bool = False
    kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None


@dataclass
class Features:
    today: date
    health: dict[date, DayHealth] = field(default_factory=dict)
    intake: dict[date, DayIntake] = field(default_factory=dict)
    # (ngày, kg) theo thời gian tăng dần, mỗi ngày một lần cân.
    weights: list[tuple[date, float]] = field(default_factory=list)
    waist: tuple[date, float] | None = None


@dataclass(frozen=True)
class Signal:
    rule: str
    severity: c.Severity
    direction: str
    value: float
    threshold: float
    anchor: date
    window: str
    title: str
    fact: str
    advice: str
    evidence: tuple[tuple[date, float], ...] = ()
    basis: tuple[str, ...] = ()

    @property
    def meta(self) -> c.Rule:
        return c.RULES[self.rule]

    @property
    def sources(self) -> list[c.Source]:
        return [c.SOURCES[key] for key in self.meta.sources]

    def features(self) -> dict[str, Any]:
        """Những gì LLM và hộp thư được thấy: số đã tính, ngưỡng, bằng chứng và nguồn."""
        meta = self.meta
        return {
            "rule": self.rule, "group": meta.group, "severity": self.severity, "metric": meta.metric,
            "unit": meta.unit, "direction": self.direction, "value": self.value, "threshold": self.threshold,
            "window": self.window, "evidence": [{"date": day.isoformat(), "value": value} for day, value in self.evidence],
            "basis": list(self.basis), "fact": self.fact, "advice": self.advice,
            "sources": [{"org": s.org, "title": s.title, "year": s.year, "url": s.url, "tier": s.tier}
                        for s in self.sources],
        }


# ---------------------------------------------------------------------------- tiện ích

def vn(value: float, digits: int = 0) -> str:
    """Số kiểu Việt Nam: 1.234,5."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def ddmm(day: date) -> str:
    return f"{day:%d/%m}"


def hm(minutes: float) -> str:
    minutes = int(round(minutes))
    return f"{minutes // 60}h{minutes % 60:02d}"


def _days(start: date, count: int) -> list[date]:
    return [start - timedelta(days=offset) for offset in range(count)]


def _consecutive(features: Features, attr: str, count: int) -> list[tuple[date, float]] | None:
    """`count` ngày liền nhau có giá trị, kết thúc hôm nay hoặc (khi hôm nay chưa có) hôm qua."""
    def value(day: date):
        row = features.health.get(day)
        return getattr(row, attr) if row is not None else None

    end = features.today if value(features.today) is not None else features.today - timedelta(days=1)
    found = [(day, value(day)) for day in _days(end, count)]
    if any(item is None for _, item in found):
        return None
    return [(day, float(item)) for day, item in found]


def _complete(features: Features, days: Iterable[date], attr: str) -> list[tuple[date, float]]:
    found = []
    for day in days:
        row = features.intake.get(day)
        if row is not None and row.complete and row.kcal is not None and getattr(row, attr) is not None:
            found.append((day, float(getattr(row, attr))))
    return found


def _slope_per_day(points: list[tuple[date, float]]) -> float:
    """Độ dốc bình phương tối thiểu (kg/ngày); không bị trễ như trung bình trượt."""
    origin = points[0][0]
    xs = [(day - origin).days for day, _ in points]
    ys = [weight for _, weight in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var if var else 0.0


def _weight_window(features: Features) -> list[tuple[date, float]] | None:
    if not features.weights:
        return None
    last = features.weights[-1][0]
    if (features.today - last).days > 7:
        return None  # lần cân gần nhất đã cũ: không nói gì về tốc độ hiện tại
    window = [(day, kg) for day, kg in features.weights if (last - day).days <= 30]
    if len(window) < c.WEIGHT_MIN_WEIGHINS or (last - window[0][0]).days < c.WEIGHT_WINDOW_MIN_DAYS:
        return None
    return window


def _list(values: Iterable[float], unit: str = "", digits: int = 0) -> str:
    return ", ".join(f"{vn(value, digits)}{unit}" for value in values)


# ---------------------------------------------------------------------------- luật

def rhr_high(f: Features, p: Profile) -> Signal | None:
    days = _consecutive(f, "rhr", 2)
    if days is None or not all(value > c.RHR_HIGH_BPM for _, value in days):
        return None
    latest = days[0]
    return Signal("rhr_high", "warn", "high", latest[1], c.RHR_HIGH_BPM, latest[0], "2 ngày liền",
                  "Nhịp tim nghỉ cao hơn bình thường",
                  f"Nhịp tim nghỉ 2 ngày gần nhất là {_list((v for _, v in reversed(days)), ' bpm')}, trên mức "
                  f"{c.RHR_HIGH_BPM} bpm (bình thường ở người lớn là 60–100 bpm).",
                  "Nghỉ ngơi, uống đủ nước và tránh tập nặng hôm nay. Nếu nhịp tim còn cao nhiều ngày, hãy đi khám.",
                  tuple(reversed(days)))


def rhr_low(f: Features, p: Profile) -> Signal | None:
    threshold = c.RHR_LOW_TRAINED_BPM if p.trained else c.RHR_LOW_BPM
    days = _consecutive(f, "rhr", 2)
    if days is None or not all(value < threshold for _, value in days):
        return None
    latest = days[0]
    basis = ("người tập luyện thường xuyên",) if p.trained else ()
    return Signal("rhr_low", "info" if p.trained else "warn", "low", latest[1], threshold, latest[0], "2 ngày liền",
                  "Nhịp tim nghỉ thấp",
                  f"Nhịp tim nghỉ 2 ngày gần nhất là {_list((v for _, v in reversed(days)), ' bpm')}, dưới mức "
                  f"{threshold} bpm.",
                  "Nhịp chậm có thể bình thường ở người tập luyện nhiều. Nếu kèm chóng mặt, mệt hoặc ngất, hãy đi khám.",
                  tuple(reversed(days)), basis)


def spo2_low(f: Features, p: Profile) -> Signal | None:
    night = _consecutive(f, "spo2", 1)
    if night is None:
        return None
    day, value = night[0]
    if value < c.SPO2_URGENT_PCT:
        return Signal("spo2_low", "urgent", "low", value, c.SPO2_URGENT_PCT, day, "đêm qua",
                      "SpO2 khi ngủ rất thấp",
                      f"SpO2 trung bình khi ngủ đêm {ddmm(day)} là {vn(value, 1)}%, dưới {c.SPO2_URGENT_PCT}% "
                      "(mức WHO coi là thiếu oxy máu).",
                      "Kiểm tra thiết bị đeo có vừa và sát da không. Nếu đo lại vẫn thấp, hoặc bạn thấy khó thở, "
                      "hãy đi khám sớm.", ((day, value),))
    days = _consecutive(f, "spo2", 2)
    if days is None or not all(item < c.SPO2_LOW_PCT for _, item in days):
        return None
    return Signal("spo2_low", "warn", "low", days[0][1], c.SPO2_LOW_PCT, days[0][0], "2 đêm liền",
                  "SpO2 khi ngủ thấp hơn bình thường",
                  f"SpO2 trung bình khi ngủ 2 đêm gần nhất là {_list((v for _, v in reversed(days)), '%', 1)}, "
                  f"dưới {c.SPO2_LOW_PCT}% (giới hạn dưới của mức bình thường theo WHO).",
                  "Kiểm tra lại cách đeo thiết bị khi ngủ. Nếu vẫn thấp thêm vài đêm hoặc bạn ngáy, ngưng thở khi ngủ, "
                  "hãy hỏi ý kiến bác sĩ.", tuple(reversed(days)))


def sleep_short(f: Features, p: Profile) -> Signal | None:
    need, of = c.SLEEP_SHORT_NIGHTS
    low = p.recommended_sleep[0]
    nights = [(day, f.health[day].sleep_minutes) for day in _days(f.today, of)
              if day in f.health and f.health[day].sleep_minutes is not None]
    short = [(day, float(minutes)) for day, minutes in nights if minutes < low * 60]
    if len(short) < need:
        return None
    hours = round(sum(minutes for _, minutes in short) / len(short) / 60, 1)
    return Signal("sleep_short", "info", "low", hours, low, nights[0][0], f"{need} trong {of} đêm gần nhất",
                  "Bạn đang ngủ ít hơn khuyến nghị",
                  f"{len(short)} trong {of} đêm gần nhất bạn ngủ dưới {vn(low)} giờ "
                  f"({', '.join(hm(minutes) for _, minutes in reversed(short))}).",
                  "Thử đi ngủ sớm hơn 30 phút và giữ giờ thức dậy cố định, kể cả cuối tuần.",
                  tuple(reversed(short)), (f"khuyến nghị {vn(low)}–{vn(p.recommended_sleep[1])} giờ theo tuổi",))


def weight_loss_fast(f: Features, p: Profile) -> Signal | None:
    window = _weight_window(f)
    if window is None:
        return None
    per_month = -_slope_per_day(window) * 30
    if per_month <= c.WEIGHT_LOSS_KG_PER_MONTH:
        return None
    span = (window[-1][0] - window[0][0]).days
    value = round(per_month, 1)
    basis = ("mục tiêu giảm mỡ",) if p.goal == "fat_loss" else ()
    return Signal("weight_loss_fast", "warn", "high", value, c.WEIGHT_LOSS_KG_PER_MONTH, window[-1][0],
                  f"{span} ngày qua", "Cân nặng giảm nhanh",
                  f"Theo {len(window)} lần cân trong {span} ngày qua, cân nặng đang giảm khoảng {vn(value, 1)} kg/tháng, "
                  f"nhanh hơn mức 2–3 kg/tháng Bộ Y tế khuyến nghị.",
                  "Tăng nhẹ năng lượng ăn vào và giữ đủ đạm để giảm từ từ, tránh mất cơ."
                  if p.goal == "fat_loss" else
                  "Bạn không đặt mục tiêu giảm cân: nếu không chủ động ăn ít hơn, hãy theo dõi thêm và hỏi ý kiến bác sĩ.",
                  tuple(window[-4:]), basis)


def weight_gain_fast(f: Features, p: Profile) -> Signal | None:
    if p.goal != "muscle_gain":
        return None
    window = _weight_window(f)
    if window is None:
        return None
    per_week = _slope_per_day(window) * 7 / window[0][1] * 100
    if per_week <= c.WEIGHT_GAIN_PCT_PER_WEEK:
        return None
    span = (window[-1][0] - window[0][0]).days
    value = round(per_week, 2)
    return Signal("weight_gain_fast", "info", "high", value, c.WEIGHT_GAIN_PCT_PER_WEEK, window[-1][0],
                  f"{span} ngày qua", "Tăng cân nhanh hơn kế hoạch tăng cơ",
                  f"Theo {len(window)} lần cân trong {span} ngày qua, cân nặng tăng khoảng {vn(value, 2)}% mỗi tuần, "
                  f"trên mức {vn(c.WEIGHT_GAIN_PCT_PER_WEEK, 1)}%/tuần khuyến nghị khi tăng cơ.",
                  "Bớt khoảng 100–200 kcal mỗi ngày để phần tăng thêm chủ yếu là cơ, ít mỡ.",
                  tuple(window[-4:]), ("mục tiêu tăng cơ",))


def bmi_band(f: Features, p: Profile) -> Signal | None:
    if p.height_cm is None or len(f.weights) < 2 or (f.today - f.weights[-1][0]).days > 7:
        return None
    meters = p.height_cm / 100
    (_, before), (day, now) = f.weights[-2], f.weights[-1]
    old, new = before / meters ** 2, now / meters ** 2
    old_band, new_band = c.bmi_band(old), c.bmi_band(new)
    if old_band == new_band:
        return None
    labels = [label for _, label in c.BMI_BANDS]
    old_at, new_at, normal = labels.index(old_band), labels.index(new_band), labels.index("Bình thường")
    toward_normal = abs(new_at - normal) < abs(old_at - normal)
    value = round(new, 1)
    return Signal("bmi_band", "info", "high" if new_at > old_at else "low", value, round(old, 1), day,
                  "lần cân mới nhất",
                  f"BMI chuyển sang nhóm {new_band}",
                  f"BMI hiện tại {vn(value, 1)} (lần cân trước {vn(old, 1)}), thuộc nhóm {new_band} theo phân loại "
                  "cho người châu Á của Bộ Y tế.",
                  "Giữ nhịp như hiện tại." if toward_normal else
                  "Theo dõi cân nặng hằng tuần và bám sát mục tiêu năng lượng.",
                  ((f.weights[-2][0], round(old, 1)), (day, value)))


def waist_high(f: Features, p: Profile) -> Signal | None:
    if f.waist is None or p.sex not in c.WAIST_HIGH_CM or (f.today - f.waist[0]).days > 30:
        return None
    day, cm = f.waist
    threshold = c.WAIST_HIGH_CM[p.sex]
    if cm < threshold:
        return None
    sex = "nam" if p.sex == "MALE" else "nữ"
    return Signal("waist_high", "info", "high", cm, threshold, day, "lần đo mới nhất",
                  "Vòng bụng trên ngưỡng khuyến nghị",
                  f"Vòng bụng {vn(cm, 1)} cm (đo ngày {ddmm(day)}). Bộ Y tế xem vòng bụng từ {vn(threshold)} cm trở "
                  f"lên ở {sex} là béo bụng.",
                  "Kết hợp vận động ít nhất 150 phút mỗi tuần với kiểm soát năng lượng để giảm mỡ bụng.",
                  ((day, cm),), (sex,))


def intake_low(f: Features, p: Profile) -> Signal | None:
    day = f.today - timedelta(days=1)
    found = _complete(f, [day], "kcal")
    if not found:
        return None
    kcal = found[0][1]
    floor = max(c.INTAKE_FLOOR_KCAL.get(p.sex, c.INTAKE_FLOOR_KCAL[None]), p.bmr_kcal or 0)
    if kcal >= floor:
        return None
    return Signal("intake_low", "warn", "low", round(kcal), round(floor), day, "hôm qua", "Hôm qua bạn ăn quá ít",
                  f"Hôm qua ({ddmm(day)}) bạn ăn {vn(kcal)} kcal, thấp hơn mức tối thiểu {vn(floor)} kcal "
                  "(năng lượng nghỉ của cơ thể hoặc mức sàn khi không có giám sát y tế).",
                  "Thêm một bữa phụ giàu đạm. Ăn quá ít kéo dài dễ gây mất cơ, mệt mỏi và khó giữ cân về sau.",
                  ((day, round(kcal)),))


def intake_off_target(f: Features, p: Profile) -> Signal | None:
    if p.target_kcal is None or p.goal not in ("fat_loss", "muscle_gain"):
        return None
    need, of = c.OFF_TARGET_DAYS
    days = _complete(f, _days(f.today - timedelta(days=1), of), "kcal")
    target = p.target_kcal
    if p.goal == "fat_loss":
        off = [(day, kcal) for day, kcal in days if kcal > target * (1 + c.OFF_TARGET_FRACTION)]
        title, direction, word = "Năng lượng ăn vào vượt mục tiêu giảm mỡ", "high", "trên"
        advice = "Giảm bớt đồ uống có đường, đồ chiên và món ăn vặt; ưu tiên rau và đạm nạc để no lâu."
    else:
        off = [(day, kcal) for day, kcal in days if kcal < target * (1 - c.OFF_TARGET_FRACTION)]
        title, direction, word = "Năng lượng ăn vào thấp hơn mục tiêu tăng cơ", "low", "dưới"
        advice = "Thêm một bữa phụ (sữa, trứng, các loại hạt) để đủ năng lượng cho cơ phát triển."
    if len(off) < need:
        return None
    average = round(sum(kcal for _, kcal in off) / len(off))
    goal = "giảm mỡ" if p.goal == "fat_loss" else "tăng cơ"
    return Signal("intake_off_target", "info", direction, average, round(target), off[0][0],
                  f"{need} trong {of} ngày gần nhất", title,
                  f"{len(off)} trong {of} ngày ghi đủ bữa gần nhất bạn ăn trung bình {vn(average)} kcal, {word} mục tiêu "
                  f"{vn(target)} kcal hơn {round(c.OFF_TARGET_FRACTION * 100)}%.",
                  advice, tuple(reversed(off)), (f"mục tiêu {goal}",))


def deficit_aggressive(f: Features, p: Profile) -> Signal | None:
    days = _days(f.today - timedelta(days=1), c.DEFICIT_DAYS)
    pairs = []
    for day, kcal in _complete(f, days, "kcal"):
        out = f.health.get(day).energy_out if day in f.health else None
        if out is not None:
            pairs.append((day, out - kcal))
    if len(pairs) < c.DEFICIT_DAYS:
        return None
    average = round(sum(gap for _, gap in pairs) / len(pairs))
    if average <= c.DEFICIT_MAX_KCAL:
        return None
    return Signal("deficit_aggressive", "warn", "high", average, c.DEFICIT_MAX_KCAL, pairs[0][0],
                  f"{c.DEFICIT_DAYS} ngày gần nhất", "Thâm hụt năng lượng quá lớn",
                  f"{c.DEFICIT_DAYS} ngày gần nhất bạn tiêu hao nhiều hơn ăn vào trung bình {vn(average)} kcal/ngày, "
                  f"vượt mức thâm hụt {vn(c.DEFICIT_MAX_KCAL)} kcal/ngày.",
                  "Ăn thêm khoảng 300–500 kcal mỗi ngày; thâm hụt quá lớn làm mất cơ và khó duy trì.",
                  tuple((day, round(gap)) for day, gap in reversed(pairs)))


def protein_low(f: Features, p: Profile) -> Signal | None:
    if not f.weights:
        return None
    weight = f.weights[-1][1]
    trained = p.trained or p.goal == "muscle_gain"
    per_kg = c.PROTEIN_TRAINED_G_PER_KG if trained else c.PROTEIN_MIN_G_PER_KG
    need, of = c.PROTEIN_DAYS
    days = _complete(f, _days(f.today - timedelta(days=1), of), "protein_g")
    low = [(day, round(grams / weight, 2)) for day, grams in days if grams / weight < per_kg]
    if len(low) < need:
        return None
    average = round(sum(value for _, value in low) / len(low), 2)
    basis = ("người tập luyện thường xuyên" if p.trained else "mục tiêu tăng cơ",) if trained else ()
    return Signal("protein_low", "info", "low", average, per_kg, low[0][0], f"{need} trong {of} ngày gần nhất",
                  "Bạn đang thiếu đạm",
                  f"{len(low)} trong {of} ngày ghi đủ bữa gần nhất lượng đạm chỉ khoảng {vn(average, 2)} g/kg, dưới mức "
                  f"{vn(per_kg, 1)} g/kg (khoảng {vn(per_kg * weight)} g với cân nặng {vn(weight, 1)} kg).",
                  "Thêm một phần đạm vào mỗi bữa: trứng, cá, thịt nạc, đậu phụ hoặc sữa.",
                  tuple(reversed(low)), basis)


def fat_high(f: Features, p: Profile) -> Signal | None:
    days = _complete(f, _days(f.today - timedelta(days=1), 7), "fat_g")
    if len(days) < c.FAT_MIN_DAYS:
        return None
    kcal = sum(f.intake[day].kcal or 0 for day, _ in days)
    if kcal <= 0:
        return None
    pct = round(sum(fat for _, fat in days) * 9 / kcal * 100, 1)
    if pct <= c.FAT_MAX_ENERGY_PCT:
        return None
    return Signal("fat_high", "info", "high", pct, c.FAT_MAX_ENERGY_PCT, days[0][0], "7 ngày qua",
                  "Chất béo chiếm tỉ lệ cao",
                  f"Trong {len(days)} ngày ghi đủ bữa gần nhất, chất béo chiếm {vn(pct, 1)}% năng lượng, trên mức dưới "
                  f"{vn(c.FAT_MAX_ENERGY_PCT)}% Bộ Y tế khuyến nghị.",
                  "Ưu tiên luộc, hấp thay cho chiên xào; dùng ít dầu mỡ và da, mỡ động vật.",
                  tuple(reversed(days)))


def fiber_low(f: Features, p: Profile) -> Signal | None:
    need, of = c.FIBER_DAYS
    days = _complete(f, _days(f.today - timedelta(days=1), of), "fiber_g")
    low = [(day, round(grams, 1)) for day, grams in days if grams < c.FIBER_MIN_G]
    if len(low) < need:
        return None
    average = round(sum(value for _, value in low) / len(low), 1)
    return Signal("fiber_low", "info", "low", average, c.FIBER_MIN_G, low[0][0], f"{need} trong {of} ngày gần nhất",
                  "Bữa ăn đang thiếu chất xơ",
                  f"{len(low)} trong {of} ngày ghi đủ bữa gần nhất bạn chỉ ăn khoảng {vn(average, 1)} g chất xơ mỗi ngày, "
                  f"dưới mức {vn(c.FIBER_MIN_G)}–30 g Bộ Y tế khuyến nghị.",
                  "Thêm rau xanh, trái cây cả vỏ, đậu và ngũ cốc nguyên hạt vào các bữa.",
                  tuple(reversed(low)))


def activity_low(f: Features, p: Profile) -> Signal | None:
    days = _days(f.today - timedelta(days=1), 7)
    worn = [(day, float(f.health[day].active_zone_minutes)) for day in days
            if day in f.health and f.health[day].active_zone_minutes is not None]
    if len(worn) < c.ACTIVITY_MIN_WORN_DAYS:
        return None
    threshold = c.ACTIVITY_MINOR_MIN_PER_WEEK if p.minor else c.ACTIVITY_MIN_PER_WEEK
    week = round(sum(minutes for _, minutes in worn) * 7 / len(worn))
    if week >= threshold:
        return None
    basis = ("dưới 18 tuổi: trung bình 60 phút mỗi ngày",) if p.minor else ()
    return Signal("activity_low", "info", "low", week, threshold, days[0], "7 ngày qua", "Tuần này vận động chưa đủ",
                  f"7 ngày qua bạn có khoảng {vn(week)} phút vận động vừa–mạnh (phút vùng tim), dưới mức {vn(threshold)} "
                  "phút mỗi tuần.",
                  "Thêm 2–3 buổi đi bộ nhanh 30 phút, hoặc chia nhỏ 10–15 phút sau các bữa ăn.",
                  tuple(reversed(worn)), basis)


def steps_low(f: Features, p: Profile) -> Signal | None:
    from domains.health_records.schemas.health import WORN_DAY_MIN_STEPS

    days = _days(f.today - timedelta(days=1), c.STEPS_DAYS)
    steps = [(day, f.health[day].steps) for day in days if day in f.health and f.health[day].steps is not None]
    if len(steps) < c.STEPS_DAYS or any(value < WORN_DAY_MIN_STEPS or value >= c.STEPS_LOW for _, value in steps):
        return None
    average = round(sum(value for _, value in steps) / len(steps))
    return Signal("steps_low", "info", "low", average, c.STEPS_LOW, days[0], f"{c.STEPS_DAYS} ngày liền",
                  "Mấy ngày nay bạn ít di chuyển",
                  f"{c.STEPS_DAYS} ngày gần nhất bạn đi {_list(value for _, value in reversed(steps))} bước, dưới mức "
                  f"{vn(c.STEPS_LOW)} bước mỗi ngày.",
                  "Đứng dậy đi lại 5 phút mỗi giờ ngồi, hoặc đi bộ sau bữa tối.",
                  tuple((day, float(value)) for day, value in reversed(steps)))


CHECKS: dict[str, Callable[[Features, Profile], Signal | None]] = {
    "rhr_high": rhr_high, "rhr_low": rhr_low, "spo2_low": spo2_low, "sleep_short": sleep_short,
    "weight_loss_fast": weight_loss_fast, "weight_gain_fast": weight_gain_fast, "bmi_band": bmi_band,
    "waist_high": waist_high, "intake_low": intake_low, "intake_off_target": intake_off_target,
    "deficit_aggressive": deficit_aggressive, "protein_low": protein_low, "fat_high": fat_high,
    "fiber_low": fiber_low, "activity_low": activity_low, "steps_low": steps_low,
}


def evaluate(features: Features, profile: Profile, groups: Iterable[str] | None = None) -> list[Signal]:
    """Các luật đang vượt ngưỡng, mức nặng trước. `groups`: nhóm người dùng muốn nhận (None = tất cả)."""
    wanted = set(groups) if groups is not None else set(c.GROUPS)
    found = []
    for rule_id, check in CHECKS.items():
        rule = c.RULES[rule_id]
        if rule.group not in wanted or (profile.minor and not rule.minors):
            continue
        signal = check(features, profile)
        if signal is not None:
            found.append(signal)
    return sorted(found, key=lambda signal: -c.SEVERITY_RANK[signal.severity])
