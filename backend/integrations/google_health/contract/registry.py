"""Registry khả năng có phiên bản: mỗi loại dữ liệu Google Health một `DataTypeSpec`.

Nguồn, được tests/test_google_health_contract.py kiểm tra:
* Ảnh chụp discovery (contract/discovery/*.json, revision trong `DISCOVERY_REVISION`):
  schema giá trị, dạng thời gian và các union phản hồi nào (reconcile, rollUp,
  dailyRollUp) mang loại này. Đây là nguồn có thẩm quyền.
* Hướng dẫn cho nhà phát triển (developers.google.com/health/data-types và /scopes, đọc
  ngày 2026-11-01): hỗ trợ list/ghi, nhóm scope và hỗ trợ webhook, những điều
  tài liệu discovery không diễn đạt được.

`verification` cho biết một khả năng được tin tới mức nào lúc chạy:
* DOCUMENTED: hướng dẫn và discovery khớp nhau; lệnh đọc được chạy, lệnh ghi tắt cho đến khi VERIFIED.
* VERIFIED: đã chạy thử với tài khoản Google thử nghiệm thật (đặt qua
  settings.GOOGLE_HEALTH_VERIFIED_CAPABILITIES, không bao giờ tuỳ tiện sửa file này).
* CONFLICT / UNDOCUMENTED: các nguồn mâu thuẫn hoặc hướng dẫn không nhắc tới; coi là
  không hỗ trợ cho đến khi được kiểm chứng. `notes` ghi lại lý do.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

DISCOVERY_REVISION = "20261030"
GUIDE_CHECKED_ON = "2026-11-01"


class Kind(str, Enum):
    SAMPLE = "sample"        # một thời điểm: sampleTime{physicalTime, utcOffset, civilTime}
    INTERVAL = "interval"    # khoảng quan sát: interval{startTime, endTime, độ lệch, giờ địa phương}
    SESSION = "session"      # phiên gộp (giấc ngủ, buổi tập, ECG, nhật ký)
    DAILY = "daily"          # mỗi ngày địa phương một điểm: {date: {...}}
    ROLLUP_ONLY = "rollup"   # chỉ tồn tại dưới dạng giá trị rollUp / dailyRollUp
    CATALOG = "catalog"      # dữ liệu tham chiếu (thực phẩm, đơn vị thực phẩm); không có dạng thời gian


class Op(str, Enum):
    LIST = "list"
    GET = "get"
    RECONCILE = "reconcile"
    ROLLUP = "rollUp"
    DAILY_ROLLUP = "dailyRollUp"
    EXPORT_TCX = "exportExerciseTcx"
    CREATE = "create"
    PATCH = "patch"
    BATCH_DELETE = "batchDelete"


class Retention(str, Enum):
    DETAIL_90D = "detail_90d"            # chuỗi dày và chi tiết phiên
    AGGREGATE_2Y = "aggregate_2y"        # giá trị theo ngày và rollup
    RECORD_2Y = "record_2y"              # bản ghi thưa mà người dùng quan tâm (cân nặng, đường huyết, nhật ký)
    SESSION_META_2Y = "session_meta_2y"  # phần đầu của phiên; chi tiết của chúng theo DETAIL_90D


class Sensitivity(str, Enum):
    NORMAL = "normal"
    # Không bao giờ được chiếu vào knowledge graph; trợ lý chỉ nhận
    # kết quả suy ra, và chỉ khi có consent tương ứng.
    SENSITIVE = "sensitive"


class Verification(str, Enum):
    VERIFIED = "verified"
    DOCUMENTED = "documented"
    CONFLICT = "conflict"
    UNDOCUMENTED = "undocumented"


READ_OPS = frozenset({Op.LIST, Op.GET, Op.RECONCILE, Op.ROLLUP, Op.DAILY_ROLLUP, Op.EXPORT_TCX})
WRITE_OPS = frozenset({Op.CREATE, Op.PATCH, Op.BATCH_DELETE})
# Giới hạn trang và khoảng lấy từ mô tả phương thức trong discovery.
LIST_PAGE_MAX = 10_000
SESSION_PAGE_MAX = 25            # buổi tập và giấc ngủ
DAILY_ROLLUP_PAGE_MAX = 90
SHORT_RANGE_TYPES = frozenset({"calories-in-heart-rate-zone", "heart-rate", "active-minutes", "total-calories"})
SHORT_RANGE_DAYS = 14            # khoảng rollUp / dailyRollUp và cỡ trang theo ngày cho SHORT_RANGE_TYPES
LONG_RANGE_DAYS = 90


@dataclass(frozen=True)
class DataTypeSpec:
    id: str
    kind: Kind
    scope_group: str
    family: str                                  # nơi dữ liệu đổ vào bảng nghiệp vụ (xem FAMILIES)
    read_ops: frozenset[Op] = frozenset()
    write_ops: frozenset[Op] = frozenset()
    webhook: bool = False
    api_versions: tuple[str, ...] = ("v4", "v4beta")
    retention: Retention = Retention.AGGREGATE_2Y
    sensitivity: Sensitivity = Sensitivity.NORMAL
    export_group: str | None = None
    verification: Verification = Verification.DOCUMENTED
    notes: str = ""
    units: dict[str, str] = field(default_factory=dict)

    @property
    def field_name(self) -> str:
        head, *rest = self.id.split("-")
        return head + "".join(part.title() for part in rest)

    @property
    def filter_path(self) -> str:
        """Filter dùng đường dẫn trường snake_case (AIP-160); URL dùng id dạng kebab-case."""
        return self.id.replace("-", "_")

    @property
    def readable(self) -> bool:
        return bool(self.read_ops)

    @property
    def write_only(self) -> bool:
        return not self.read_ops and bool(self.write_ops)

    @property
    def max_range_days(self) -> int:
        return SHORT_RANGE_DAYS if self.id in SHORT_RANGE_TYPES else LONG_RANGE_DAYS

    @property
    def list_page_size(self) -> int:
        return SESSION_PAGE_MAX if self.id in ("sleep", "exercise") else LIST_PAGE_MAX

    @property
    def daily_rollup_page_size(self) -> int:
        return SHORT_RANGE_DAYS if self.id in SHORT_RANGE_TYPES else DAILY_ROLLUP_PAGE_MAX

    def supports(self, op: Op) -> bool:
        return op in self.read_ops or op in self.write_ops


FAMILIES = {
    "daily_summary": "daily_health_summaries columns (per civil date)",
    "series": "health_series_chunks (dense samples or intervals, compressed)",
    "sleep_session": "sleep_sessions (+ stages, short awakenings)",
    "device_workout": "device_workouts (+ splits, pauses, route)",
    "body_metric": "body_metrics (weight, height, body fat)",
    "vital_sample": "health_samples (sparse vitals)",
    "ecg": "ecg_recordings (classification kept; waveform never reaches prompts or graph)",
    "irn": "irn_alerts",
    "hydration_log": "hydration_logs",
    "nutrition_log": "nutrition_logs",
    "wellbeing_log": "symptom/mood/menstrual/ovulation logs (write-only at Google)",
    "catalog": "provider food catalog references",
}

_R = frozenset
L, G, REC, RU, DRU = Op.LIST, Op.GET, Op.RECONCILE, Op.ROLLUP, Op.DAILY_ROLLUP
WRITE = WRITE_OPS
ACT, MET = "activity_and_fitness", "health_metrics_and_measurements"
D90, A2Y, R2Y, S2Y = Retention.DETAIL_90D, Retention.AGGREGATE_2Y, Retention.RECORD_2Y, Retention.SESSION_META_2Y
SENS = Sensitivity.SENSITIVE


def _specs() -> Iterable[DataTypeSpec]:
    I, S, SE, DA = Kind.INTERVAL, Kind.SAMPLE, Kind.SESSION, Kind.DAILY
    # --- vận động và thể chất -------------------------------------------------
    yield DataTypeSpec("steps", I, ACT, "series", _R({L, G, REC, RU, DRU}), webhook=True, retention=D90,
                       units={"count": "steps"})
    yield DataTypeSpec("distance", I, ACT, "series", _R({L, G, REC, RU, DRU}), webhook=True, retention=D90,
                       units={"millimeters": "mm"})
    yield DataTypeSpec("floors", I, ACT, "series", _R({G, REC, RU, DRU}), webhook=True, retention=D90,
                       notes="Guide lists no `list`; discovery exposes it in the DataPoint union only.")
    yield DataTypeSpec("altitude", I, ACT, "series", _R({L, G, REC, RU, DRU}), webhook=True, retention=D90)
    yield DataTypeSpec("active-minutes", I, ACT, "series", _R({L, G, REC, RU, DRU}), webhook=True, retention=D90)
    yield DataTypeSpec("active-zone-minutes", I, ACT, "series", _R({L, G, REC, RU, DRU}), webhook=True,
                       retention=D90)
    yield DataTypeSpec("active-energy-burned", I, ACT, "series", _R({L, G, REC, RU, DRU}), retention=D90,
                       units={"kcal": "kcal"})
    yield DataTypeSpec("basal-energy-burned", I, ACT, "series", _R({L, G, REC}), retention=D90,
                       verification=Verification.UNDOCUMENTED,
                       notes="In the discovery DataPoint/ReconciledDataPoint unions, absent from the guide's table.")
    yield DataTypeSpec("activity-level", DA, ACT, "series", _R({L, G, REC, RU, DRU}), webhook=True, retention=D90,
                       notes="Discovery calls it a daily collection although points carry an interval.")
    yield DataTypeSpec("sedentary-period", I, ACT, "series", _R({L, G, REC, RU, DRU}), webhook=True, retention=D90)
    yield DataTypeSpec("time-in-heart-rate-zone", I, ACT, "series", _R({L, G, REC, RU, DRU}), webhook=True,
                       retention=D90)
    yield DataTypeSpec("swim-lengths-data", I, ACT, "series", _R({L, G, REC, RU, DRU}), retention=D90)
    yield DataTypeSpec("total-calories", Kind.ROLLUP_ONLY, ACT, "daily_summary", _R({RU, DRU}), retention=A2Y,
                       units={"kcalSum": "kcal"})
    yield DataTypeSpec("calories-in-heart-rate-zone", Kind.ROLLUP_ONLY, ACT, "daily_summary", _R({RU, DRU}),
                       webhook=True, retention=A2Y)
    yield DataTypeSpec("vo2-max", S, ACT, "vital_sample", _R({L, G, REC}), retention=R2Y)
    yield DataTypeSpec("run-vo2-max", S, ACT, "vital_sample", _R({L, G, REC, RU, DRU}), webhook=True, retention=R2Y)
    yield DataTypeSpec("daily-vo2-max", DA, ACT, "daily_summary", _R({L, G, REC}), retention=A2Y)
    yield DataTypeSpec("exercise", SE, ACT, "device_workout", _R({L, G, REC, Op.EXPORT_TCX}), WRITE, webhook=True,
                       retention=S2Y, export_group="workout",
                       notes="Route (TCX) additionally needs googlehealth.location.readonly.")
    # --- chỉ số sức khoẻ và số đo ------------------------------------------------
    yield DataTypeSpec("heart-rate", S, MET, "series", _R({L, G, REC, RU, DRU}), webhook=True, retention=D90,
                       units={"beatsPerMinute": "bpm"})
    yield DataTypeSpec("heart-rate-variability", S, MET, "series", _R({L, G, REC}), webhook=True, retention=D90,
                       units={"rootMeanSquareOfSuccessiveDifferencesMilliseconds": "ms"})
    yield DataTypeSpec("oxygen-saturation", S, MET, "series", _R({L, G, REC}), retention=D90,
                       units={"percentage": "%"})
    yield DataTypeSpec("respiratory-rate-sleep-summary", S, MET, "vital_sample", _R({L, G, REC}), webhook=True,
                       retention=R2Y)
    yield DataTypeSpec("weight", S, MET, "body_metric", _R({L, G, REC, RU, DRU}), WRITE, webhook=True,
                       retention=R2Y, export_group="body", units={"weightGrams": "g"})
    yield DataTypeSpec("height", S, MET, "body_metric", _R({L, G, REC}), WRITE, webhook=True, retention=R2Y,
                       export_group="body", units={"heightMillimeters": "mm"})
    yield DataTypeSpec("body-fat", S, MET, "body_metric", _R({L, G, REC, RU, DRU}), WRITE, webhook=True,
                       retention=R2Y, export_group="body", units={"percentage": "%"})
    yield DataTypeSpec("blood-glucose", S, MET, "vital_sample", _R({L, G, REC, RU, DRU}), webhook=True,
                       retention=R2Y, sensitivity=SENS, units={"bloodGlucoseMilligramsPerDeciliter": "mg/dL"})
    yield DataTypeSpec("core-body-temperature", S, MET, "vital_sample", _R({L, G, REC, RU, DRU}), retention=R2Y,
                       units={"temperatureCelsius": "C"})
    for daily in ("daily-resting-heart-rate", "daily-heart-rate-variability", "daily-oxygen-saturation",
                  "daily-respiratory-rate", "daily-sleep-temperature-derivations", "daily-heart-rate-zones"):
        yield DataTypeSpec(daily, DA, MET, "daily_summary", _R({L, G, REC}), webhook=True, retention=A2Y)
    yield DataTypeSpec("skin-temperature-sensors", S, MET, "series", _R({L, G, REC}), api_versions=("v4beta",),
                       retention=D90, notes="v4beta only; enable per type through GH_V4BETA_TYPES. Discovery "
                                            "lists reconcile, the guide's table does not.")
    # --- giấc ngủ, ECG, IRN -----------------------------------------------------
    yield DataTypeSpec("sleep", SE, "sleep", "sleep_session", _R({L, G, REC}), WRITE, webhook=True, retention=S2Y,
                       export_group="sleep", notes="Stages and short awakenings overlap; never sum them blindly.")
    yield DataTypeSpec("electrocardiogram", SE, "ecg", "ecg", _R({L, G}), retention=S2Y, sensitivity=SENS,
                       notes="Keep the provider classification; the waveform never enters prompts or the graph.")
    yield DataTypeSpec("irregular-rhythm-notification", SE, "irn", "irn", _R({L, G}), retention=S2Y,
                       sensitivity=SENS)
    # --- dinh dưỡng -------------------------------------------------------------
    # Sự tồn tại của scope được chứng minh lúc chạy: lệnh đọc chỉ chạy khi Google cấp nó.
    nutrition_note = ("Guide documents googlehealth.nutrition.readonly; the discovery snapshot lists only "
                      "nutrition.writeonly for these methods.")
    yield DataTypeSpec("hydration-log", SE, "nutrition", "hydration_log", _R({L, G, REC, RU, DRU}), WRITE,
                       webhook=True, retention=R2Y, export_group="hydration", notes=nutrition_note)
    yield DataTypeSpec("nutrition-log", SE, "nutrition", "nutrition_log", _R({L, G, REC, RU, DRU}), WRITE,
                       webhook=True, retention=R2Y, export_group="nutrition", notes=nutrition_note)
    yield DataTypeSpec("food", Kind.CATALOG, "nutrition", "catalog", _R({L, G}), retention=R2Y, notes=nutrition_note)
    yield DataTypeSpec("food-measurement-unit", Kind.CATALOG, "nutrition", "catalog", _R({L, G}), retention=R2Y, notes=nutrition_note)
    # --- nhật ký chỉ ghi (không nhập được lịch sử) -------------------------------
    write_only = "Write-only at Google: HercFit owns the log; no history import is possible."
    yield DataTypeSpec("symptoms", S, "logged_symptoms", "wellbeing_log", write_ops=WRITE, retention=R2Y,
                       sensitivity=SENS, export_group="symptoms", notes=write_only)
    yield DataTypeSpec("moods", S, "mindfulness", "wellbeing_log", write_ops=WRITE, retention=R2Y,
                       sensitivity=SENS, export_group="mood", notes=write_only)
    yield DataTypeSpec("menstrual-period", I, "reproductive_health", "wellbeing_log", write_ops=WRITE,
                       retention=R2Y, sensitivity=SENS, export_group="reproductive", notes=write_only)
    yield DataTypeSpec("ovulation-test", S, "reproductive_health", "wellbeing_log", write_ops=WRITE, retention=R2Y,
                       sensitivity=SENS, export_group="reproductive", notes=write_only)


DATA_TYPES: dict[str, DataTypeSpec] = {spec.id: spec for spec in _specs()}
EXPORT_GROUPS: dict[str, tuple[str, ...]] = {}
for _spec in DATA_TYPES.values():
    if _spec.export_group:
        EXPORT_GROUPS.setdefault(_spec.export_group, ())
        EXPORT_GROUPS[_spec.export_group] += (_spec.id,)
# Thứ tự được phép bật các nhóm xuất (M6): rủi ro thấp trước.
EXPORT_ROLLOUT = ("body", "hydration", "nutrition", "workout", "sleep", "symptoms", "mood", "reproductive")


def spec(data_type: str) -> DataTypeSpec:
    try:
        return DATA_TYPES[data_type]
    except KeyError:
        raise KeyError(f"Unknown Google Health data type {data_type!r}") from None


def runtime_enabled(data_type: str, op: Op, *, verified: frozenset[str] = frozenset(),
                    api_version: str = "v4") -> bool:
    """HercFit có được chạy `op` trên loại này lúc này không? Lệnh ghi cần kiểm chứng tường minh.

    `verified` chứa các khoá khả năng "data-type:op" đã xác nhận bằng tài khoản thật
    (settings.GOOGLE_HEALTH_VERIFIED_CAPABILITIES).
    """
    item = spec(data_type)
    if api_version not in item.api_versions or not item.supports(op):
        return False
    if f"{data_type}:{op.value}" in verified:
        return True
    if op in WRITE_OPS:
        return False
    return item.verification in (Verification.DOCUMENTED, Verification.VERIFIED)


def by_family(family: str) -> list[DataTypeSpec]:
    return [item for item in DATA_TYPES.values() if item.family == family]
