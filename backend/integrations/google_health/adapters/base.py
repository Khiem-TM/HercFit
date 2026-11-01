"""Phân tích payload Google Health dựa trên schema.

Ảnh chụp discovery khai báo kiểu của mọi trường: giá trị int64 đến dưới dạng
chuỗi JSON, thời lượng dạng "3.5s", mốc thời gian RFC 3339, ngày dạng {year, month,
day}, giờ địa phương không kèm độ lệch, cùng các enum. Adapter chuyển đổi đúng
các khai báo đó thay vì đoán mò theo khoá, và báo cáo:

* `unknown_paths`: các trường có trong payload nhưng không có trong schema
  (được giữ trong payload nguồn đã lưu; hiển thị thành cảnh báo schema),
* `quality[path]`: BAD_TYPE, UNKNOWN_ENUM hoặc OUT_OF_RANGE cho trường có
  mặt nhưng không tin được (khi đó giá trị có kiểu của nó là None).

Trường bị thiếu thì đơn giản là vắng mặt: "không có dữ liệu" và "bằng 0" vẫn phân biệt được.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from integrations.google_health.contract import discovery
from integrations.google_health.contract.registry import Kind, spec

BAD_TYPE, UNKNOWN_ENUM, OUT_OF_RANGE = "BAD_TYPE", "UNKNOWN_ENUM", "OUT_OF_RANGE"
_NANOS = re.compile(r"(\.\d{6})\d+")

# Ngưỡng hợp lý cho các giá trị nuôi cột nghiệp vụ (đường dẫn bên trong đối tượng giá trị).
PLAUSIBLE: dict[tuple[str, str], tuple[float, float]] = {
    ("heart-rate", "beatsPerMinute"): (20, 300),
    ("daily-resting-heart-rate", "beatsPerMinute"): (20, 250),
    ("weight", "weightGrams"): (2_000, 700_000),
    ("height", "heightMillimeters"): (300, 3_000),
    ("body-fat", "percentage"): (1, 80),
    ("blood-glucose", "bloodGlucoseMilligramsPerDeciliter"): (10, 900),
    ("core-body-temperature", "temperatureCelsius"): (25, 45),
    ("oxygen-saturation", "percentage"): (50, 100),
    ("daily-oxygen-saturation", "averagePercentage"): (50, 100),
    ("daily-respiratory-rate", "breathsPerMinute"): (2, 80),
    ("daily-heart-rate-variability", "averageHeartRateVariabilityMilliseconds"): (0, 1000),
    ("heart-rate-variability", "rootMeanSquareOfSuccessiveDifferencesMilliseconds"): (0, 1000),
    ("vo2-max", "vo2Max"): (5, 100), ("daily-vo2-max", "vo2Max"): (5, 100), ("run-vo2-max", "runVo2Max"): (5, 100),
}


@dataclass
class TimeInfo:
    """Giờ vật lý, độ lệch UTC mà Google ghi và giờ địa phương (giờ đồng hồ) được giữ tách biệt."""
    physical_start: datetime | None = None
    physical_end: datetime | None = None
    start_offset_s: int | None = None
    end_offset_s: int | None = None
    civil_start: datetime | None = None   # giờ đồng hồ không kèm múi giờ
    civil_end: datetime | None = None
    civil_date: date | None = None        # các loại theo ngày

    def local_start(self) -> datetime | None:
        """Thời điểm bắt đầu theo giờ đồng hồ: giờ địa phương của Google, nếu không thì giờ vật lý dịch theo độ lệch đã ghi."""
        if self.civil_start is not None:
            return self.civil_start
        if self.physical_start is not None and self.start_offset_s is not None:
            return (self.physical_start + timedelta(seconds=self.start_offset_s)).replace(tzinfo=None)
        return None

    def local_end(self) -> datetime | None:
        if self.civil_end is not None:
            return self.civil_end
        if self.physical_end is not None and self.end_offset_s is not None:
            return (self.physical_end + timedelta(seconds=self.end_offset_s)).replace(tzinfo=None)
        return None


@dataclass
class Parsed:
    data_type: str
    api_version: str
    resource_name: str | None
    value: dict[str, Any]
    time: TimeInfo
    data_source: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, str] = field(default_factory=dict)
    unknown_paths: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.quality and not self.unknown_paths

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.value
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def warnings(self) -> list[str]:
        return [f"unknown:{path}" for path in self.unknown_paths] + [f"{code}:{path}" for path, code in self.quality.items()]


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(_NANOS.sub(r"\1", value.replace("Z", "+00:00")))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def parse_duration(value: Any) -> float | None:
    """JSON Duration của Protobuf ("3.5s", "-25200s")."""
    if isinstance(value, str) and value.endswith("s"):
        try:
            return float(value[:-1])
        except ValueError:
            return None
    return None


def _date(value: Any) -> date | None:
    if not isinstance(value, dict):
        return None
    try:
        return date(int(value["year"]), int(value["month"]), int(value["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def _civil(value: Any) -> datetime | None:
    if not isinstance(value, dict):
        return None
    day = _date(value.get("date"))
    if day is None:
        return None
    clock = value.get("time") or {}
    try:
        return datetime(day.year, day.month, day.day, int(clock.get("hours", 0)), int(clock.get("minutes", 0)),
                        int(clock.get("seconds", 0)), int(clock.get("nanos", 0)) // 1000)
    except (TypeError, ValueError):
        return None


class SchemaAdapter:
    """Phân tích payload của một phiên bản API theo các schema discovery của nó."""

    def __init__(self, api_version: str = "v4"):
        self.api_version = api_version
        self._schemas = discovery.schemas(api_version)

    # -- chuyển đổi có kiểu tổng quát ----------------------------------------------------------
    def convert(self, schema_name: str, payload: Any, path: str = "", *, quality: dict[str, str],
                unknown: list[str]) -> Any:
        if schema_name == "Date":
            result = _date(payload)
            if result is None:
                quality[path or schema_name] = BAD_TYPE
            return result
        if schema_name == "CivilDateTime":
            result = _civil(payload)
            if result is None:
                quality[path or schema_name] = BAD_TYPE
            return result
        schema = self._schemas[schema_name]
        if not isinstance(payload, dict):
            quality[path or schema_name] = BAD_TYPE
            return None
        properties = schema.get("properties", {})
        result: dict[str, Any] = {}
        for key, raw in payload.items():
            child = f"{path}.{key}" if path else key
            prop = properties.get(key)
            if prop is None:
                unknown.append(child)
                continue
            result[key] = self._field(prop, raw, child, quality, unknown)
        return result

    def _field(self, prop: dict[str, Any], raw: Any, path: str, quality: dict[str, str], unknown: list[str]) -> Any:
        if "$ref" in prop:
            return self.convert(prop["$ref"], raw, path, quality=quality, unknown=unknown)
        kind, fmt = prop.get("type"), prop.get("format")
        if kind == "array":
            if not isinstance(raw, list):
                quality[path] = BAD_TYPE
                return None
            return [self._field(prop["items"], item, f"{path}[{index}]", quality, unknown)
                    for index, item in enumerate(raw)]
        if kind == "string":
            if not isinstance(raw, str):
                quality[path] = BAD_TYPE
                return None
            if fmt in ("int64", "uint64"):
                try:
                    return int(raw)
                except ValueError:
                    quality[path] = BAD_TYPE
                    return None
            if fmt == "google-datetime":
                moment = parse_timestamp(raw)
                if moment is None:
                    quality[path] = BAD_TYPE
                return moment
            if fmt == "google-duration":
                seconds = parse_duration(raw)
                if seconds is None:
                    quality[path] = BAD_TYPE
                return seconds
            if prop.get("enum") and raw not in prop["enum"]:
                quality[path] = UNKNOWN_ENUM
            return raw
        if kind in ("number", "integer"):
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                # Trong trường hợp hiếm Google có thể mã hoá int32/double thành chuỗi; chấp nhận chữ số chính xác.
                try:
                    raw = float(raw) if kind == "number" else int(raw)
                except (TypeError, ValueError):
                    quality[path] = BAD_TYPE
                    return None
            if kind == "number" and raw != raw:  # NaN
                quality[path] = BAD_TYPE
                return None
            return float(raw) if kind == "number" else int(raw)
        if kind == "boolean":
            if not isinstance(raw, bool):
                quality[path] = BAD_TYPE
                return None
            return raw
        if kind == "object":
            return raw  # dạng tự do (Operation.response, metadata)
        return raw

    # -- data point ---------------------------------------------------------------------------------
    def value_schema(self, data_type: str) -> str:
        info = discovery.data_point_types(self.api_version).get(data_type)
        if info is not None:
            return info["schema"]
        rollup = discovery.rollup_value_schema(data_type, daily=False, version=self.api_version)
        if rollup is None:
            raise KeyError(f"{data_type} has no data point schema in {self.api_version}")
        return rollup

    def parse_point(self, data_type: str, point: dict[str, Any]) -> Parsed:
        """Phân tích một data point từ list/get/reconcile (`DataPoint` hoặc `ReconciledDataPoint`)."""
        quality: dict[str, str] = {}
        unknown: list[str] = []
        field_name = discovery.camel(data_type)
        known_envelope = {"name", "dataPointName", "dataSource", field_name}
        for key in point:
            if key not in known_envelope:
                unknown.append(key)
        raw_value = point.get(field_name)
        value = self.convert(self.value_schema(data_type), raw_value, field_name, quality=quality, unknown=unknown) \
            if raw_value is not None else None
        if raw_value is None:
            quality[field_name] = BAD_TYPE
            value = {}
        source = self.convert("DataSource", point["dataSource"], "dataSource", quality=quality, unknown=unknown) \
            if isinstance(point.get("dataSource"), dict) else {}
        self._plausible(data_type, value or {}, quality, prefix=field_name)
        return Parsed(data_type=data_type, api_version=self.api_version,
                      resource_name=point.get("name") or point.get("dataPointName"),
                      value=value or {}, time=self._time(data_type, value or {}),
                      data_source=source or {}, quality=quality, unknown_paths=unknown)

    def parse_rollup(self, data_type: str, point: dict[str, Any], *, daily: bool) -> Parsed:
        """Phân tích một cửa sổ rollUp / dailyRollUp: mốc cửa sổ cộng giá trị rollup của loại này."""
        quality: dict[str, str] = {}
        unknown: list[str] = []
        field_name = discovery.camel(data_type)
        window = ("civilStartTime", "civilEndTime") if daily else ("startTime", "endTime")
        for key in point:
            if key not in (*window, field_name):
                unknown.append(key)
        schema = discovery.rollup_value_schema(data_type, daily=daily, version=self.api_version)
        raw = point.get(field_name)
        value = self.convert(schema, raw, field_name, quality=quality, unknown=unknown) \
            if schema and raw is not None else {}
        time = TimeInfo()
        if daily:
            time.civil_start, time.civil_end = _civil(point.get("civilStartTime")), _civil(point.get("civilEndTime"))
            time.civil_date = time.civil_start.date() if time.civil_start else None
        else:
            time.physical_start, time.physical_end = parse_timestamp(point.get("startTime")), parse_timestamp(point.get("endTime"))
        return Parsed(data_type=data_type, api_version=self.api_version, resource_name=None, value=value or {},
                      time=time, quality=quality, unknown_paths=unknown)

    def _time(self, data_type: str, value: dict[str, Any]) -> TimeInfo:
        kind = spec(data_type).kind if data_type in _registry_ids() else None
        time = TimeInfo()
        sample = value.get("sampleTime")
        interval = value.get("interval")
        if isinstance(sample, dict):
            time.physical_start = time.physical_end = sample.get("physicalTime")
            time.start_offset_s = time.end_offset_s = _int(sample.get("utcOffset"))
            time.civil_start = time.civil_end = sample.get("civilTime")
        elif isinstance(interval, dict):
            time.physical_start, time.physical_end = interval.get("startTime"), interval.get("endTime")
            time.start_offset_s, time.end_offset_s = _int(interval.get("startUtcOffset")), _int(interval.get("endUtcOffset"))
            time.civil_start, time.civil_end = interval.get("civilStartTime"), interval.get("civilEndTime")
        if isinstance(value.get("date"), date):
            time.civil_date = value["date"]
        elif kind is not Kind.CATALOG:
            # Giấc ngủ thuộc ngày thức dậy; mọi thứ khác thuộc ngày bắt đầu.
            local = time.local_end() if data_type == "sleep" else time.local_start()
            time.civil_date = local.date() if local else None
        return time

    @staticmethod
    def _plausible(data_type: str, value: dict[str, Any], quality: dict[str, str], prefix: str) -> None:
        for (owner, path), (low, high) in PLAUSIBLE.items():
            if owner != data_type:
                continue
            number = value.get(path)
            if isinstance(number, (int, float)) and not low <= number <= high:
                value[path] = None
                quality[f"{prefix}.{path}"] = OUT_OF_RANGE


def _int(seconds: float | None) -> int | None:
    return int(seconds) if seconds is not None else None


def _registry_ids() -> frozenset[str]:
    from integrations.google_health.contract.registry import DATA_TYPES
    return frozenset(DATA_TYPES)


_ADAPTERS: dict[str, SchemaAdapter] = {}


def adapter(api_version: str = "v4") -> SchemaAdapter:
    if api_version not in _ADAPTERS:
        _ADAPTERS[api_version] = SchemaAdapter(api_version)
    return _ADAPTERS[api_version]
