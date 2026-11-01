"""Payload adapters per API version.

Stable v4 is the default. A v4beta adapter is used only for data types that are
both v4beta-capable in the registry and listed in settings.GH_V4BETA_TYPES,
and only once they have contract fixtures (M7).
"""
from pathlib import Path

from integrations.google_health.adapters.base import Parsed, SchemaAdapter, TimeInfo, adapter
from integrations.google_health.contract.registry import spec


FIXTURES = Path(__file__).resolve().parents[1] / "contract" / "fixtures"


def has_beta_contract(data_type: str) -> bool:
    """v4beta is used for a type only once a contract fixture pins its payload (M7)."""
    return (FIXTURES / f"v4beta_{data_type}.json").exists()


def api_version_for(data_type: str, v4beta_types: frozenset[str] | set[str] = frozenset()) -> str:
    item = spec(data_type)
    beta = data_type in v4beta_types and "v4beta" in item.api_versions and has_beta_contract(data_type)
    if "v4" not in item.api_versions:
        return "v4beta" if beta else ""
    return "v4beta" if beta else "v4"


def adapter_for(data_type: str, v4beta_types: frozenset[str] | set[str] = frozenset()) -> SchemaAdapter | None:
    version = api_version_for(data_type, v4beta_types)
    return adapter(version) if version else None


__all__ = ["Parsed", "SchemaAdapter", "TimeInfo", "adapter", "adapter_for", "api_version_for"]
