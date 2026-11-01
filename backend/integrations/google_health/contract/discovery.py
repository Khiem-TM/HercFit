"""Read-only access to the snapshotted Google Health discovery documents.

The snapshot (discovery/v4.json, discovery/v4beta.json) is the machine-readable
contract: value schemas, field types and formats (int64 strings, durations,
timestamps), enums and the data types each API version knows. Refresh it with
`python -m scripts.snapshot_discovery`; tests fail when the registry and the
snapshot disagree.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent / "discovery"
API_VERSIONS = ("v4", "v4beta")
KIND_PATTERN = re.compile(r"`([a-z0-9-]+)` (sample|interval|session|daily) data type")
WINDOW_FIELDS = {"startTime", "endTime", "civilStartTime", "civilEndTime"}


@lru_cache(maxsize=None)
def document(version: str = "v4") -> dict[str, Any]:
    if version not in API_VERSIONS:
        raise ValueError(f"Unknown Google Health API version {version!r}")
    return json.loads((DIRECTORY / f"{version}.json").read_text())


def revision(version: str = "v4") -> str:
    return str(document(version).get("revision"))


def schemas(version: str = "v4") -> dict[str, Any]:
    return document(version)["schemas"]


def camel(data_type: str) -> str:
    head, *rest = data_type.split("-")
    return head + "".join(part.title() for part in rest)


def kebab(field: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z0-9])", "-", field).lower().replace("-2", "2").replace("vo-2", "vo2")


@lru_cache(maxsize=None)
def data_point_types(version: str = "v4") -> dict[str, dict[str, str]]:
    """data type id -> {"field", "schema", "kind"} for every DataPoint union member."""
    result: dict[str, dict[str, str]] = {}
    for field, spec in schemas(version)["DataPoint"]["properties"].items():
        match = KIND_PATTERN.search(spec.get("description", ""))
        if match and spec.get("$ref"):
            result[match.group(1)] = {"field": field, "schema": spec["$ref"], "kind": match.group(2)}
    return result


@lru_cache(maxsize=None)
def union_fields(schema_name: str, version: str = "v4") -> frozenset[str]:
    """Union members of a response schema such as ReconciledDataPoint or RollupDataPoint."""
    properties = schemas(version)[schema_name]["properties"]
    return frozenset(name for name in properties if name not in WINDOW_FIELDS | {"dataPointName", "name", "dataSource"})


def rollup_value_schema(data_type: str, *, daily: bool, version: str = "v4") -> str | None:
    holder = "DailyRollupDataPoint" if daily else "RollupDataPoint"
    spec = schemas(version)[holder]["properties"].get(camel(data_type))
    return spec.get("$ref") if spec else None


def scopes(version: str = "v4") -> frozenset[str]:
    return frozenset(document(version)["auth"]["oauth2"]["scopes"])


def method(path: tuple[str, ...], name: str, version: str = "v4") -> dict[str, Any]:
    node = document(version)
    for resource in path:
        node = node["resources"][resource]
    return node["methods"][name]
