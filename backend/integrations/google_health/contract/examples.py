"""Deterministic, schema-valid synthetic payloads built from the discovery snapshot.

They exercise the adapters for every data type without a Google account. They
are synthetic: values are plausible placeholders, not recordings. Hand-written
fixtures under contract/fixtures/ cover the semantics (time zones, DST, nights
across midnight, unit conversion) that a schema alone cannot.
"""
from __future__ import annotations

from typing import Any

from integrations.google_health.contract import discovery

PHYSICAL = "2026-10-30T01:02:03Z"
PHYSICAL_END = "2026-10-30T02:02:03Z"
OFFSET = "25200s"  # UTC+7
CIVIL = {"date": {"year": 2026, "month": 10, "day": 30}, "time": {"hours": 8, "minutes": 2, "seconds": 3}}
CIVIL_END = {"date": {"year": 2026, "month": 10, "day": 30}, "time": {"hours": 9, "minutes": 2, "seconds": 3}}
NUMBERS = {
    "weightGrams": 70_500.0, "heightMillimeters": "1720", "percentage": 21.5, "beatsPerMinute": "62",
    "bloodGlucoseMilligramsPerDeciliter": 96.0, "temperatureCelsius": 36.8, "averagePercentage": 96.5,
    "breathsPerMinute": 14.2, "averageHeartRateVariabilityMilliseconds": 48.0, "vo2Max": 45.0, "runVo2Max": 46.0,
    "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 41.0,
}


def example(schema_name: str, version: str = "v4", *, depth: int = 0, key: str = "") -> Any:
    if schema_name == "Date":
        return dict(CIVIL["date"])
    if schema_name == "CivilDateTime":
        return {"date": dict(CIVIL["date"]), "time": dict(CIVIL["time"])}
    if schema_name == "TimeOfDay":
        return dict(CIVIL["time"])
    schema = discovery.schemas(version)[schema_name]
    result: dict[str, Any] = {}
    for name, prop in schema.get("properties", {}).items():
        if prop.get("readOnly") and name not in ("civilTime", "civilStartTime", "civilEndTime"):
            continue
        value = _value(prop, version, depth, name)
        if value is not None:
            result[name] = value
    return result


def _value(prop: dict[str, Any], version: str, depth: int, name: str) -> Any:
    if "$ref" in prop:
        if depth > 4:
            return None
        if prop["$ref"] == "CivilDateTime" and "End" in name:
            return {"date": dict(CIVIL_END["date"]), "time": dict(CIVIL_END["time"])}
        return example(prop["$ref"], version, depth=depth + 1, key=name)
    kind, fmt = prop.get("type"), prop.get("format")
    if kind == "array":
        item = _value(prop["items"], version, depth + 1, name)
        return [item] if item is not None else []
    if name in NUMBERS:
        return NUMBERS[name]
    if kind == "string":
        if fmt in ("int64", "uint64"):
            return "30"
        if fmt == "google-datetime":
            return PHYSICAL_END if "end" in name.lower() else PHYSICAL
        if fmt == "google-duration":
            return OFFSET if "Offset" in name or name == "utcOffset" else "1800s"
        if prop.get("enum"):
            options = [value for value in prop["enum"] if not value.endswith("UNSPECIFIED")]
            return options[0] if options else prop["enum"][0]
        return f"example-{name}"
    if kind == "number":
        return 1.5
    if kind == "integer":
        return 3
    if kind == "boolean":
        return name in ("mainSleep",)
    return None


def data_point(data_type: str, version: str = "v4") -> dict[str, Any]:
    info = discovery.data_point_types(version)[data_type]
    return {"name": f"users/me/dataTypes/{data_type}/dataPoints/example-1",
            "dataSource": {"recordingMethod": "PASSIVELY_MEASURED", "platform": "FITBIT",
                           "device": {"formFactor": "WATCH", "manufacturer": "Google", "displayName": "Pixel Watch"}},
            info["field"]: example(info["schema"], version)}


def rollup_point(data_type: str, *, daily: bool, version: str = "v4") -> dict[str, Any]:
    schema = discovery.rollup_value_schema(data_type, daily=daily, version=version)
    window = ({"civilStartTime": {"date": dict(CIVIL["date"])}, "civilEndTime": {"date": {"year": 2026, "month": 10, "day": 31}}}
              if daily else {"startTime": PHYSICAL, "endTime": PHYSICAL_END})
    return {**window, discovery.camel(data_type): example(schema, version)}
