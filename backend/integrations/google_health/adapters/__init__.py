"""Adapter payload theo phiên bản API.

v4 ổn định là mặc định. Adapter v4beta chỉ dùng cho các loại dữ liệu
vừa hỗ trợ v4beta trong registry vừa được liệt kê trong settings.GH_V4BETA_TYPES,
và chỉ khi đã có fixture hợp đồng (M7).
"""
from pathlib import Path

from integrations.google_health.adapters.base import Parsed, SchemaAdapter, TimeInfo, adapter
from integrations.google_health.contract.registry import spec


FIXTURES = Path(__file__).resolve().parents[1] / "contract" / "fixtures"


def has_beta_contract(data_type: str) -> bool:
    """v4beta chỉ được dùng cho một loại khi đã có fixture hợp đồng ghim payload của nó (M7)."""
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
