"""Google Health OAuth scopes and the feature bundles HercFit asks for incrementally.

Only scopes listed on developers.google.com/health/scopes (checked 2026-11-01)
are ever requested: an unknown scope fails the whole consent. Discovery also
lists `.readonly` variants for logged_symptoms, mindfulness and
reproductive_health that the guide does not document; they stay out of every
request until verified.

Three permissions stay separate:
* the Google grant (these scopes, held in health_connections.granted_scopes),
* HercFit export settings (google_export_settings, per export group),
* consent for the assistant to read the data (user_consents).
"""
from __future__ import annotations

from dataclasses import dataclass

PREFIX = "https://www.googleapis.com/auth/googlehealth."
IDENTITY_SCOPES = ("openid", "email")

# Scope groups with the variants the guide documents.
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
# In the discovery snapshot but not in the guide: never requested automatically.
DISCOVERY_ONLY = frozenset({
    PREFIX + "logged_symptoms.readonly", PREFIX + "mindfulness.readonly", PREFIX + "reproductive_health.readonly",
})
# In the guide but not in the discovery snapshot (existence proven only by a grant).
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
    """A feature the user can turn on; HercFit asks only for its scopes, when needed."""
    key: str
    label_vi: str
    scopes: tuple[str, ...]
    sensitive: bool = False


BUNDLES: dict[str, Bundle] = {bundle.key: bundle for bundle in (
    # Reading (the default connect flow asks for CORE_READ only).
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
    # Writing (asked only when the user enables an export group).
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
