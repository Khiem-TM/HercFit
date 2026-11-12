"""Năm interface làm việc với Google Health: Interval, Sample, Daily, Session, Food.

Mỗi interface ứng với một dạng bản ghi của Google và lo ba việc:
* `filter(t, start, end)`: filter AIP-160 cho list/reconcile theo ngày địa phương, chỉ dùng
  `>=` và `<` nối bằng AND (đúng ngữ pháp đã mô tả của phương thức list);
* `parse(t, raw, zone)`: DataPoint / ReconciledDataPoint / DailyRollupDataPoint → `HealthPoint`;
* `build_*`: payload DataPoint cho lệnh ghi.

Giá trị Google được giữ nguyên (đối tượng union của data point); domains/health_records/views.py
ánh xạ nó sang chỉ số HercFit. Ngày địa phương lấy từ giờ đồng hồ Google ghi kèm (civil time),
thiếu thì dịch giờ vật lý theo độ lệch UTC đã ghi (reconcile không trả civil time cho buổi tập),
thiếu cả hai thì dùng múi giờ của người dùng.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from domains.health_records.types import FOOD_UNITS, DataType, Kind, Read, number

MANUAL = {"recordingMethod": "MANUAL"}
MAX_AHEAD = timedelta(hours=14)  # UTC+14: cận dưới vật lý không bao giờ bỏ sót một ngày địa phương
_NANOS = re.compile(r"(\.\d{6})\d+")


@dataclass(frozen=True)
class HealthPoint:
    data_type: str
    kind: str
    local_date: date
    value: dict[str, Any]
    remote_name: str
    start_at: datetime | None = None
    end_at: datetime | None = None

    def row(self, user_id: UUID, *, written_by_hercfit: bool = False) -> dict[str, Any]:
        return {"user_id": user_id, "data_type": self.data_type, "kind": self.kind, "start_at": self.start_at,
                "end_at": self.end_at, "local_date": self.local_date, "value": self.value,
                "remote_name": self.remote_name, "written_by_hercfit": written_by_hercfit}


# ------------------------------------------------------------------------------ chuyển kiểu JSON
def timestamp(value: Any) -> datetime | None:
    """RFC 3339 (có thể tới nano giây) → datetime có múi giờ."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(_NANOS.sub(r"\1", value.replace("Z", "+00:00")))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def seconds(value: Any) -> float | None:
    """Duration của Protobuf ("1800s", "-25200s")."""
    return number(value) if isinstance(value, str) and value.endswith("s") else None


def day(value: Any) -> date | None:
    """Date của Google: {year, month, day}."""
    try:
        return date(int(value["year"]), int(value["month"]), int(value["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def civil(value: Any) -> datetime | None:
    """CivilDateTime của Google: {date, time?} không kèm múi giờ."""
    if not isinstance(value, dict) or (when := day(value.get("date"))) is None:
        return None
    clock = value.get("time") or {}
    try:
        return datetime(when.year, when.month, when.day, int(clock.get("hours", 0)), int(clock.get("minutes", 0)),
                        int(clock.get("seconds", 0)))
    except (TypeError, ValueError):
        return None


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def offset(moment: datetime, zone: str) -> str:
    return f"{int(moment.astimezone(ZoneInfo(zone)).utcoffset().total_seconds())}s"


def _local(moment: datetime | None, utc_offset: Any, civil_time: Any, zone: str) -> date | None:
    if (clock := civil(civil_time)) is not None:
        return clock.date()
    if moment is None:
        return None
    if (shift := seconds(utc_offset)) is not None:
        return (moment.astimezone(timezone.utc) + timedelta(seconds=shift)).date()
    return moment.astimezone(ZoneInfo(zone)).date()


def _range(path: str, start: date, end: date) -> str:
    return f'{path} >= "{start.isoformat()}" AND {path} < "{end.isoformat()}"'


def _name(t: DataType, raw: dict[str, Any], moment: datetime) -> str:
    return raw.get("dataPointName") or raw.get("name") or f"{t.id}:{stamp(moment)}"


# ------------------------------------------------------------------------------ năm interface
class Interval:
    """Dữ liệu theo khoảng thời gian: startTime, endTime và giá trị (số bước từ 8:00 → 9:00)."""

    @staticmethod
    def filter(t: DataType, start: date, end: date) -> str:
        return _range(f"{t.path}.interval.civil_start_time", start, end)

    @staticmethod
    def interval(start: datetime, end: datetime, zone: str) -> dict[str, str]:
        return {"startTime": stamp(start), "startUtcOffset": offset(start, zone),
                "endTime": stamp(end), "endUtcOffset": offset(end, zone)}

    @classmethod
    def parse(cls, t: DataType, raw: dict[str, Any], zone: str) -> HealthPoint | None:
        value = raw.get(t.field)
        if not isinstance(value, dict):
            return None
        span = value.get("interval") or {}
        start, end = timestamp(span.get("startTime")), timestamp(span.get("endTime"))
        if start is None:
            return None
        # Một đêm thuộc ngày người dùng thức dậy; mọi thứ khác thuộc ngày bắt đầu.
        key = "end" if t.id == "sleep" and end is not None else "start"
        local = _local(end if key == "end" else start, span.get(f"{key}UtcOffset"),
                       span.get(f"civil{key.title()}Time"), zone)
        if local is None:
            return None
        if t.id == "electrocardiogram":
            # Dạng sóng không bao giờ được lưu, đưa vào prompt hay graph; chỉ giữ phân loại và metadata.
            value = {name: item for name, item in value.items() if name != "waveformSamples"}
        return HealthPoint(t.id, t.stored_kind, local, value, _name(t, raw, start), start, end or start)


class Session(Interval):
    """Một phiên hoạt động: buổi tập 6:00 – 6:45, giấc ngủ, lần uống nước, bữa ăn, ECG."""

    @staticmethod
    def filter(t: DataType, start: date, end: date) -> str:
        if t.id == "sleep":
            return _range("sleep.interval.civil_end_time", start, end)
        if t.id == "electrocardiogram":
            # ECG chỉ cho lọc cận dưới theo giờ vật lý; bên gọi bỏ các điểm sau cửa sổ.
            lower = datetime.combine(start, time.min, timezone.utc) - MAX_AHEAD
            return f'electrocardiogram.interval.start_time >= "{stamp(lower)}"'
        return _range(f"{t.path}.interval.civil_start_time", start, end)

    @classmethod
    def build_exercise(cls, *, start: datetime, end: datetime, zone: str, exercise_type: str, name: str,
                       active_seconds: float | None = None, kcal: float | None = None,
                       distance_m: float | None = None, notes: str | None = None) -> dict[str, Any]:
        """Chỉ tóm tắt phiên mà HercFit thật sự có; không bao giờ bịa nhịp tim hay bước chân."""
        summary: dict[str, Any] = {}
        if kcal is not None:
            summary["caloriesKcal"] = round(float(kcal), 1)
        if distance_m:
            summary["distanceMillimeters"] = round(float(distance_m) * 1000)
        value: dict[str, Any] = {"interval": cls.interval(start, end, zone), "exerciseType": exercise_type,
                                 "displayName": name[:255], "metricsSummary": summary}
        if active_seconds:
            value["activeDuration"] = f"{int(active_seconds)}s"
        if notes:
            value["notes"] = notes[:1000]
        return {"dataSource": MANUAL, "exercise": value}

    @classmethod
    def build_sleep(cls, *, start: datetime, end: datetime, zone: str) -> dict[str, Any]:
        """Giấc ngủ ghi tay: chỉ giờ ngủ và giờ dậy người dùng khai, một đoạn ASLEEP (kiểu CLASSIC).

        Không bịa giai đoạn hay lần thức giấc; summary là trường output-only do Google tự tính.
        """
        span = cls.interval(start, end, zone)
        stage = {"type": "ASLEEP", "startTime": span["startTime"], "startUtcOffset": span["startUtcOffset"],
                 "endTime": span["endTime"], "endUtcOffset": span["endUtcOffset"]}
        return {"dataSource": MANUAL, "sleep": {"type": "CLASSIC", "interval": span, "stages": [stage]}}

    @classmethod
    def build_hydration(cls, *, moment: datetime, zone: str, milliliters: float) -> dict[str, Any]:
        return {"dataSource": MANUAL, "hydrationLog": {
            "interval": cls.interval(moment, moment + timedelta(minutes=1), zone),
            "amountConsumed": {"milliliters": round(float(milliliters), 1), "userProvidedUnit": "MILLILITER"}}}


class Sample:
    """Dữ liệu tại một thời điểm: sampleTime và giá trị (cân nặng lúc 07:15)."""
    # loại: (trường, hệ số từ đơn vị HercFit kg / cm / %)
    BODY = {"weight": ("weightGrams", 1000.0), "height": ("heightMillimeters", 10.0), "body-fat": ("percentage", 1.0)}

    @staticmethod
    def filter(t: DataType, start: date, end: date) -> str:
        return _range(f"{t.path}.sample_time.civil_time", start, end)

    @staticmethod
    def parse(t: DataType, raw: dict[str, Any], zone: str) -> HealthPoint | None:
        value = raw.get(t.field)
        if not isinstance(value, dict):
            return None
        sample = value.get("sampleTime") or {}
        moment = timestamp(sample.get("physicalTime"))
        local = _local(moment, sample.get("utcOffset"), sample.get("civilTime"), zone)
        if moment is None or local is None:
            return None
        return HealthPoint(t.id, Kind.SAMPLE, local, value, _name(t, raw, moment), moment, moment)

    @classmethod
    def build(cls, data_type: str, *, moment: datetime, zone: str, value: float) -> dict[str, Any]:
        """Cân nặng (kg), chiều cao (cm) hoặc % mỡ → data point; heightMillimeters là int64 dạng chuỗi."""
        key, factor = cls.BODY[data_type]
        amount: Any = round(float(value) * factor, 1)
        if data_type == "height":
            amount = str(round(amount))
        field = DataType(data_type, Kind.SAMPLE, "").field
        return {"dataSource": MANUAL, field: {key: amount, "sampleTime": {
            "physicalTime": stamp(moment), "utcOffset": offset(moment, zone)}}}


class Daily:
    """Tổng hợp theo ngày: điểm daily-* ({date}) và cửa sổ dailyRollUp (civilStartTime)."""

    @staticmethod
    def filter(t: DataType, start: date, end: date) -> str:
        return _range(f"{t.path}.date", start, end)

    @staticmethod
    def parse(t: DataType, raw: dict[str, Any], zone: str) -> HealthPoint | None:
        value = raw.get(t.field)
        if not isinstance(value, dict):
            return None
        window = civil(raw.get("civilStartTime"))
        local = day(value.get("date")) or (window.date() if window else None)
        if local is None:
            return None
        # Mỗi loại một giá trị mỗi ngày: khoá tất định giữ id ổn định qua các lần đọc lại.
        return HealthPoint(t.id, Kind.DAILY, local, value, f"{t.id}:{local.isoformat()}")


class Hourly:
    """Cửa sổ rollUp theo giờ ({startTime, endTime, <giá trị>}): mỗi giờ một điểm, ngày địa phương theo múi giờ."""

    @staticmethod
    def parse(t: DataType, raw: dict[str, Any], zone: str) -> HealthPoint | None:
        value = raw.get(t.field)
        start, end = timestamp(raw.get("startTime")), timestamp(raw.get("endTime"))
        if not isinstance(value, dict) or not value or start is None:
            return None
        # Khoá tất định theo giờ bắt đầu: đọc lại cùng giờ cập nhật đúng dòng đó.
        return HealthPoint(t.id, Kind.INTERVAL, start.astimezone(ZoneInfo(zone)).date(), value,
                           f"{t.id}:{stamp(start)}", start, end or start + timedelta(hours=1))


class Food:
    """Thực phẩm, thành phần dinh dưỡng và đơn vị khẩu phần (nutrition-log, catalog đơn vị).

    HercFit ghi "thực phẩm ẩn danh" theo docs dinh dưỡng: foodDisplayName, energy, energyFromFat,
    totalCarbohydrate, totalFat và nutrients do HercFit cung cấp. Log ẩn danh không sửa được sau
    khi tạo, nên một lần sửa là xoá rồi tạo lại. Interval phải có end > start (INVALID_TIME_RANGE).
    """
    # (giờ bắt đầu, giờ kết thúc, MealType) theo giờ địa phương
    MEALS = ((4, 10, "BREAKFAST"), (10, 14, "LUNCH"), (17, 22, "DINNER"))
    ATWATER_FAT = 9.0

    @classmethod
    def meal_type(cls, moment: datetime, zone: str) -> str:
        hour = moment.astimezone(ZoneInfo(zone)).hour
        return next((meal for low, high, meal in cls.MEALS if low <= hour < high), "SNACK")

    @classmethod
    def build_nutrition_log(cls, *, name: str, start: datetime, zone: str, kcal: float | None = None,
                            carbohydrate_g: float | None = None, fat_g: float | None = None,
                            protein_g: float | None = None, fiber_g: float | None = None,
                            amount: float | None = None, unit: str | None = None,
                            minutes: int = 15) -> dict[str, Any]:
        value: dict[str, Any] = {"interval": Interval.interval(start, start + timedelta(minutes=minutes), zone),
                                 "foodDisplayName": name[:255], "mealType": cls.meal_type(start, zone)}
        # Chất chưa biết bị bỏ qua, không bao giờ gửi là 0.
        if kcal is not None:
            value["energy"] = {"kcal": round(float(kcal), 1)}
        if carbohydrate_g is not None:
            value["totalCarbohydrate"] = {"grams": round(float(carbohydrate_g), 2)}
        if fat_g is not None:
            value["totalFat"] = {"grams": round(float(fat_g), 2)}
            value["energyFromFat"] = {"kcal": round(float(fat_g) * cls.ATWATER_FAT, 1)}
        nutrients = [{"nutrient": nutrient, "quantity": {"grams": round(float(grams), 2)}}
                     for nutrient, grams in (("PROTEIN", protein_g), ("DIETARY_FIBER", fiber_g)) if grams is not None]
        if nutrients:
            value["nutrients"] = nutrients
        if amount and unit in FOOD_UNITS:
            value["serving"] = {"foodMeasurementUnit": FOOD_UNITS[unit], "amount": round(float(amount), 2)}
        return {"dataSource": MANUAL, "nutritionLog": value}


INTERFACES = {Kind.INTERVAL: Interval, Kind.SAMPLE: Sample, Kind.DAILY: Daily, Kind.SESSION: Session}


def interface(t: DataType) -> type[Interval] | type[Sample] | type[Daily] | type[Hourly]:
    if t.read is Read.HOURLY_ROLLUP:
        return Hourly
    return Daily if t.read is Read.DAILY_ROLLUP else INTERFACES[t.kind]


def parse(t: DataType, raw: dict[str, Any], zone: str) -> HealthPoint | None:
    return interface(t).parse(t, raw, zone)


def filter_for(t: DataType, start: date, end: date) -> str:
    return interface(t).filter(t, start, end)
