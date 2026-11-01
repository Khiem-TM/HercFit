"""Scope OAuth của Google Health và các gói tính năng HercFit xin dần.

Chỉ các scope liệt kê trên developers.google.com/health/scopes (kiểm tra ngày 2026-11-01)
mới được xin: một scope không rõ làm hỏng cả màn hình đồng ý. Discovery còn
liệt kê các biến thể `.readonly` cho logged_symptoms, mindfulness và
reproductive_health mà hướng dẫn không mô tả; chúng không có trong request nào
cho đến khi được kiểm chứng.

Ba loại quyền được giữ tách biệt:
* quyền Google cấp (các scope này, lưu trong health_connections.granted_scopes),
* thiết lập xuất của HercFit (google_export_settings, theo nhóm xuất),
* consent cho trợ lý đọc dữ liệu (user_consents).
"""
from __future__ import annotations

from dataclasses import dataclass

PREFIX = "https://www.googleapis.com/auth/googlehealth."
IDENTITY_SCOPES = ("openid", "email")

# Các nhóm scope với những biến thể mà hướng dẫn có mô tả.
DOCUMENTED: dict[str, tuple[str, ...]] = {
    "activity_and_fitness": ("readonly", "writeonly"),
    "health_metrics_and_measurements": ("readonly", "writeonly"),
    "sleep": ("readonly", "writeonly"),
    "nutrition": ("readonly", "writeonly"),
    "ecg": ("readonly",),
    "irn": ("readonly",),
    "location": ("readonly",),
    "profile": ("readonly", "writeonly"),
    "settings": ("readonly", "writeonly"),
    "logged_symptoms": ("writeonly",),
    "mindfulness": ("writeonly",),
    "reproductive_health": ("writeonly",),
}
# Có trong ảnh chụp discovery nhưng không có trong hướng dẫn: không bao giờ tự động xin.
DISCOVERY_ONLY = frozenset({
    PREFIX + "logged_symptoms.readonly", PREFIX + "mindfulness.readonly", PREFIX + "reproductive_health.readonly",
})
# Có trong hướng dẫn nhưng không có trong ảnh chụp discovery (chỉ chứng minh được tồn tại khi được cấp).
GUIDE_ONLY = frozenset({PREFIX + "nutrition.readonly"})


def scope(group: str, access: str) -> str:
    if access not in DOCUMENTED.get(group, ()):
        raise ValueError(f"googlehealth.{group}.{access} is not a documented scope")
    return f"{PREFIX}{group}.{access}"


def read_scope(group: str) -> str | None:
    return scope(group, "readonly") if "readonly" in DOCUMENTED.get(group, ()) else None


def write_scope(group: str) -> str | None:
    return scope(group, "writeonly") if "writeonly" in DOCUMENTED.get(group, ()) else None


ALL_DOCUMENTED = frozenset(scope(group, access) for group, accesses in DOCUMENTED.items() for access in accesses)


@dataclass(frozen=True)
class Bundle:
    """Một tính năng người dùng có thể bật; HercFit chỉ xin scope của nó, khi cần."""
    key: str
    label_vi: str
    scopes: tuple[str, ...]
    sensitive: bool = False


BUNDLES: dict[str, Bundle] = {bundle.key: bundle for bundle in (
    # Đọc (luồng kết nối mặc định chỉ xin CORE_READ).
    Bundle("activity_read", "Vận động, bước chân, buổi tập", (scope("activity_and_fitness", "readonly"),)),
    Bundle("metrics_read", "Nhịp tim, HRV, SpO₂, cân nặng, chỉ số cơ thể",
           (scope("health_metrics_and_measurements", "readonly"),)),
    Bundle("sleep_read", "Giấc ngủ", (scope("sleep", "readonly"),)),
    Bundle("profile_read", "Hồ sơ và cài đặt Google Health",
           (scope("profile", "readonly"), scope("settings", "readonly"))),
    Bundle("nutrition_read", "Nước uống và dinh dưỡng", (scope("nutrition", "readonly"),)),
    Bundle("route_read", "Lộ trình GPS của buổi tập", (scope("location", "readonly"),), sensitive=True),
    Bundle("ecg_read", "Điện tâm đồ (ECG) và cảnh báo nhịp bất thường",
           (scope("ecg", "readonly"), scope("irn", "readonly")), sensitive=True),
    # Ghi (chỉ xin khi người dùng bật một nhóm xuất).
    Bundle("body_write", "Ghi cân nặng, chiều cao, mỡ cơ thể", (scope("health_metrics_and_measurements", "writeonly"),)),
    Bundle("hydration_write", "Ghi nước uống", (scope("nutrition", "writeonly"),)),
    Bundle("nutrition_write", "Ghi bữa ăn", (scope("nutrition", "writeonly"),)),
    Bundle("workout_write", "Ghi buổi tập", (scope("activity_and_fitness", "writeonly"),)),
    Bundle("sleep_write", "Ghi giấc ngủ", (scope("sleep", "writeonly"),)),
    Bundle("symptoms_write", "Ghi triệu chứng", (scope("logged_symptoms", "writeonly"),), sensitive=True),
    Bundle("mood_write", "Ghi tâm trạng", (scope("mindfulness", "writeonly"),), sensitive=True),
    Bundle("reproductive_write", "Ghi kỳ kinh và que thử rụng trứng",
           (scope("reproductive_health", "writeonly"),), sensitive=True),
)}
CORE_READ = ("activity_read", "metrics_read", "sleep_read", "profile_read", "nutrition_read")
EXPORT_GROUP_BUNDLES = {
    "body": "body_write", "hydration": "hydration_write", "nutrition": "nutrition_write", "workout": "workout_write",
    "sleep": "sleep_write", "symptoms": "symptoms_write", "mood": "mood_write", "reproductive": "reproductive_write",
}


def bundle_scopes(keys: tuple[str, ...] | list[str]) -> list[str]:
    seen: list[str] = []
    for key in keys:
        for item in BUNDLES[key].scopes:
            if item not in seen:
                seen.append(item)
    return seen


def granted_bundles(granted: list[str] | set[str]) -> list[str]:
    owned = set(granted)
    return [key for key, bundle in BUNDLES.items() if set(bundle.scopes) <= owned]


def can_read(group: str, granted: list[str] | set[str]) -> bool:
    wanted = read_scope(group)
    return wanted is not None and wanted in set(granted)


def can_write(group: str, granted: list[str] | set[str]) -> bool:
    wanted = write_scope(group)
    return wanted is not None and wanted in set(granted)
