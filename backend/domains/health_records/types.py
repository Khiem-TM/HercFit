"""Các loại dữ liệu Google Health mà HercFit dùng, xếp theo 5 dạng bản ghi.

Nguồn: developers.google.com/health/data-types (đọc ngày 2026-11-02) và ảnh chụp discovery v4
(integrations/google_health/contract/discovery/v4.json, dùng trong test).

Mỗi loại khai báo dạng bản ghi (`kind`), cách đọc (`read`) và ai sở hữu dữ liệu (`owner`):

* GOOGLE: chỉ đọc. Chỉ thiết bị đeo đo được (giấc ngủ, nhịp tim, HRV...).
* WRITE_THROUGH: Google là nguồn sự thật. HercFit ghi thẳng lên Google (buổi thể thao, cân nặng,
  nước uống...) rồi reconcile mang về; HercFit không giữ bản riêng.
* HERCFIT: HercFit là nguồn sự thật và đẩy lên Google (buổi gym, bữa ăn); không đọc lại.

Loại interval dày (bước chân, quãng đường, calo...) chỉ đọc tổng theo ngày qua dailyRollUp nên
được lưu ở dạng DAILY; chuỗi từng phút không được lưu.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Kind(StrEnum):
    INTERVAL = "interval"   # một khoảng thời gian: startTime, endTime, giá trị (bước chân 8:00 → 9:00)
    SAMPLE = "sample"       # một thời điểm: cân nặng, VO2max, đường huyết
    DAILY = "daily"         # tổng hợp theo ngày: HRV, nhịp tim nghỉ, tổng năng lượng (TDEE)
    SESSION = "session"     # một phiên: buổi tập 6:00 – 6:45, giấc ngủ, lần uống nước, bữa ăn
    FOOD = "food"           # thực phẩm, thành phần dinh dưỡng và đơn vị khẩu phần


class Read(StrEnum):
    RECONCILE = "reconcile"        # luồng đã gộp mọi nguồn và khử trùng lặp
    LIST = "list"                  # loại không có reconcile (ECG, IRN)
    DAILY_ROLLUP = "dailyRollUp"   # tổng theo ngày địa phương
    HOURLY_ROLLUP = "rollUp"       # tổng theo từng giờ (rollUp, cửa sổ 3600 s theo thời gian thực)
    NONE = "none"                  # không đọc về


class Owner(StrEnum):
    GOOGLE = "google"
    WRITE_THROUGH = "write_through"
    HERCFIT = "hercfit"


SCOPE_PREFIX = "https://www.googleapis.com/auth/googlehealth."
ACT, MET, SLEEP, NUTRITION, ECG, IRN = (
    "activity_and_fitness", "health_metrics_and_measurements", "sleep", "nutrition", "ecg", "irn")
# Giấc ngủ ghi tay (giờ ngủ–giờ dậy) được ghi xuyên lên Google như nước uống, cân nặng.
WRITE_GROUPS = frozenset({ACT, MET, NUTRITION, SLEEP})
# dailyRollUp: heart-rate, total-calories và active-minutes chỉ cho khoảng tối đa 14 ngày.
SHORT_ROLLUP = frozenset({"heart-rate", "total-calories", "active-minutes"})
SESSION_PAGE = 25          # exercise và sleep: tối đa 25 điểm mỗi trang
PAGE = 10_000


@dataclass(frozen=True)
class DataType:
    id: str
    kind: Kind
    scope: str
    read: Read = Read.RECONCILE
    owner: Owner = Owner.GOOGLE
    sensitive: bool = False
    # Loại Google được đọc khi khác tên loại lưu trong health_points (nhịp tim theo giờ đọc từ heart-rate).
    source: str | None = None

    @property
    def google_id(self) -> str:
        return self.source or self.id

    @property
    def field(self) -> str:
        """Tên trường giá trị trong DataPoint (camelCase của id kebab-case)."""
        head, *rest = self.google_id.split("-")
        return head + "".join(part.title() for part in rest)

    @property
    def path(self) -> str:
        """Filter AIP-160 dùng snake_case."""
        return self.google_id.replace("-", "_")

    @property
    def stored_kind(self) -> Kind:
        return Kind.DAILY if self.read is Read.DAILY_ROLLUP else self.kind

    @property
    def page_size(self) -> int:
        if self.read is Read.DAILY_ROLLUP:
            return self.chunk_days
        if self.read is Read.HOURLY_ROLLUP:
            return self.chunk_days * 24
        return SESSION_PAGE if self.id in ("exercise", "sleep") else PAGE

    @property
    def chunk_days(self) -> int:
        return 14 if self.google_id in SHORT_ROLLUP else 90

    @property
    def read_scope(self) -> str:
        return f"{SCOPE_PREFIX}{self.scope}.readonly"

    @property
    def write_scope(self) -> str | None:
        return f"{SCOPE_PREFIX}{self.scope}.writeonly" if self.scope in WRITE_GROUPS else None


I, S, D, SE = Kind.INTERVAL, Kind.SAMPLE, Kind.DAILY, Kind.SESSION
ROLLUP, WT, HF = Read.DAILY_ROLLUP, Owner.WRITE_THROUGH, Owner.HERCFIT
TYPES: dict[str, DataType] = {item.id: item for item in (
    # --- vận động: tổng theo ngày ---
    DataType("steps", I, ACT, ROLLUP), DataType("distance", I, ACT, ROLLUP), DataType("floors", I, ACT, ROLLUP),
    DataType("active-minutes", I, ACT, ROLLUP), DataType("active-zone-minutes", I, ACT, ROLLUP),
    DataType("active-energy-burned", I, ACT, ROLLUP), DataType("total-calories", I, ACT, ROLLUP),
    DataType("heart-rate", S, MET, ROLLUP),
    # Cùng nhịp tim, gộp theo từng giờ (TB/thấp nhất/cao nhất) để xem phân bố trong ngày.
    DataType("heart-rate-hourly", I, MET, Read.HOURLY_ROLLUP, source="heart-rate"),
    DataType("sedentary-period", I, ACT),
    # --- chỉ số theo ngày của thiết bị ---
    DataType("daily-resting-heart-rate", D, MET), DataType("daily-heart-rate-variability", D, MET),
    DataType("daily-oxygen-saturation", D, MET), DataType("daily-respiratory-rate", D, MET),
    DataType("daily-sleep-temperature-derivations", D, MET), DataType("daily-vo2-max", D, ACT),
    # --- mẫu rời ---
    DataType("weight", S, MET, owner=WT), DataType("height", S, MET, owner=WT), DataType("body-fat", S, MET, owner=WT),
    DataType("vo2-max", S, ACT), DataType("run-vo2-max", S, ACT), DataType("respiratory-rate-sleep-summary", S, MET),
    DataType("blood-glucose", S, MET, sensitive=True), DataType("core-body-temperature", S, MET),
    # --- phiên ---
    DataType("exercise", SE, ACT, owner=WT), DataType("sleep", SE, SLEEP, owner=WT), DataType("hydration-log", SE, NUTRITION, owner=WT),
    DataType("electrocardiogram", SE, ECG, Read.LIST, sensitive=True),
    DataType("irregular-rhythm-notification", SE, IRN, Read.LIST, sensitive=True),
    DataType("nutrition-log", SE, NUTRITION, Read.NONE, HF),
    # --- thực phẩm ---
    DataType("food-measurement-unit", Kind.FOOD, NUTRITION, Read.NONE),
)}
# Nhóm dữ liệu người dùng bật/tắt đồng bộ (Hồ sơ & kết nối › Kết nối). Loại không thuộc nhóm nào
# (SpO2, nhịp thở, VO2 max, buổi vận động, nước uống...) luôn được đọc như trước.
SYNC_GROUPS: dict[str, tuple[str, ...]] = {
    "sleep": ("sleep", "daily-sleep-temperature-derivations", "respiratory-rate-sleep-summary"),
    "rhr": ("daily-resting-heart-rate", "heart-rate", "heart-rate-hourly"),
    "hrv": ("daily-heart-rate-variability",),
    "steps": ("steps", "distance", "floors", "active-minutes", "active-zone-minutes", "active-energy-burned",
              "total-calories", "sedentary-period"),
    "body": ("weight", "height", "body-fat"),
}
SYNC_FREQUENCIES = ("hourly", "open", "manual")


def disabled_types(groups: dict[str, bool] | None) -> frozenset[str]:
    """Các loại thuộc nhóm người dùng đã tắt; khoá vắng mặt nghĩa là nhóm đang bật."""
    return frozenset(data_type for group, members in SYNC_GROUPS.items()
                     if (groups or {}).get(group) is False for data_type in members)


# Loại do HercFit ghi được đánh dấu bằng một lần reconcile self-sources khi đọc.
SELF_MARKED = frozenset(item.id for item in TYPES.values() if item.owner is WT)
# Đơn vị khẩu phần trong catalog food-measurement-unit (434 đơn vị, kiểm tra trên tài khoản thật
# ngày 2026-11-02): gram 147, ml 209, serving 304. Đơn vị HercFit G/ML/SERVING ánh xạ thẳng.
FOOD_UNITS = {"G": "users/me/dataTypes/food-measurement-unit/dataPoints/147",
              "ML": "users/me/dataTypes/food-measurement-unit/dataPoints/209",
              "SERVING": "users/me/dataTypes/food-measurement-unit/dataPoints/304"}
# Một lần đồng ý: đọc các nhóm cốt lõi, ghi những gì HercFit ghi, cùng hồ sơ và cài đặt (tuổi, múi giờ).
# ECG/IRN chỉ được đọc khi người dùng đã tự cấp.
CONNECT_SCOPES = tuple(sorted({
    *(f"{SCOPE_PREFIX}{group}.readonly" for group in (ACT, MET, SLEEP, NUTRITION, "profile", "settings")),
    *(f"{SCOPE_PREFIX}{group}.writeonly" for group in WRITE_GROUPS),
}))


def number(value: Any) -> float | None:
    """Số JSON, hoặc int64 / Duration dạng chuỗi của Google ("6200", "1800s")."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value[:-1] if value.endswith("s") else value)
        except ValueError:
            return None
    return None


def spec(data_type: str) -> DataType:
    try:
        return TYPES[data_type]
    except KeyError:
        raise KeyError(f"Unknown Google Health data type {data_type!r}") from None


def readable(granted: list[str] | tuple[str, ...], skip: frozenset[str] = frozenset()) -> list[DataType]:
    scopes = set(granted)
    return [item for item in TYPES.values()
            if item.read is not Read.NONE and item.read_scope in scopes and item.id not in skip]


def can_write(data_type: str, granted: list[str] | tuple[str, ...]) -> bool:
    scope = spec(data_type).write_scope
    return scope is not None and scope in set(granted)
