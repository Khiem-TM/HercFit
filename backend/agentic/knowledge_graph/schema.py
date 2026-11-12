"""Lược đồ truy vấn được của G_K: nguồn duy nhất cho projector, prompt sinh Cypher và validator.

Mỗi nhãn khai báo phạm vi sở hữu và các thuộc tính có kiểu mà Cypher sinh ra được phép đọc. Thuộc tính nội bộ
(key, owner_id, fact_json, search_text, source_id…) không có ở đây nên không bao giờ được đọc hay trả về.

Phạm vi:
- private: mọi nút mang owner_id; validator luôn gắn {owner_id:$owner, deleted:false} vào mẫu nút.
- mixed: dữ liệu hệ thống dùng chung lẫn bản ghi riêng (Food, Exercise); chỉ đọc được khi nút đi qua quan hệ từ một
  nút đã thuộc người dùng, hoặc bị giới hạn về scope 'SYSTEM'.
- shared: dữ liệu công khai không gắn người dùng (Intent).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

# Tăng khi đổi nhãn, thuộc tính hay quan hệ: mẫu truy vấn đã học của phiên bản cũ mất hiệu lực.
SCHEMA_VERSION = 1
LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")


@dataclass(frozen=True)
class Prop:
    type: str  # date | datetime | float | int | str | bool | list
    desc: str


@dataclass(frozen=True)
class Label:
    scope: str  # private | mixed | shared
    desc: str
    props: dict = field(default_factory=dict)


def _p(type_, desc):
    return Prop(type_, desc)


NUTRITION = {
    "energy_kcal": _p("float", "năng lượng, kcal"),
    "protein_g": _p("float", "protein, g"),
    "carbohydrate_g": _p("float", "carbohydrate, g"),
    "fat_g": _p("float", "chất béo, g"),
    "fiber_g": _p("float", "chất xơ, g"),
}
RECORD_TIME = {
    "at": _p("datetime", "thời điểm (UTC)"),
    "local_date": _p("date", "ngày địa phương Asia/Ho_Chi_Minh"),
    "local_time": _p("str", "giờ địa phương 'HH:MM'"),
}

LABELS = {
    "User": Label(
        "private",
        "người dùng hiện tại",
        {
            "age": _p("int", "tuổi"),
            "sex": _p("str", "MALE | FEMALE"),
            "activity_level": _p("str", "mức vận động tự khai"),
        },
    ),
    "Meal": Label(
        "private",
        "bữa ăn đã ghi",
        {
            **RECORD_TIME,
            "name": _p("str", "tên bữa, vd. Bữa sáng/Bữa trưa/Bữa tối/Bữa phụ"),
            **NUTRITION,
            "nutrition_incomplete": _p("bool", "một số món thiếu dữ liệu dinh dưỡng"),
        },
    ),
    "MealItem": Label(
        "private",
        "một món trong bữa ăn (ảnh chụp lúc ghi)",
        {
            "food_name": _p("str", "tên món lúc ghi"),
            "quantity": _p("float", "lượng"),
            "unit": _p("str", "G | ML"),
            **NUTRITION,
        },
    ),
    "Food": Label(
        "mixed",
        "món trong catalog (dinh dưỡng trên 100 g hoặc 100 ml)",
        {
            "name_vi": _p("str", "tên tiếng Việt"),
            "name_en": _p("str", "tên tiếng Anh"),
            "name_search": _p("str", "tên không dấu, chữ thường; so khớp với $terms"),
            "category_vi": _p("str", "nhóm món"),
            "serving_unit": _p("str", "G | ML: căn cứ 100 g hay 100 ml"),
            **NUTRITION,
        },
    ),
    "Training": Label(
        "private",
        "buổi tập đã ghi",
        {
            **RECORD_TIME,
            "name": _p("str", "tên buổi"),
            "discipline": _p("str", "STRENGTH | RUNNING | ..."),
            "duration_min": _p("float", "thời lượng, phút"),
            "session_rpe": _p("float", "RPE cả buổi 1-10"),
            "training_load": _p("float", "tải sRPE = RPE × phút"),
            "energy_kcal": _p("float", "năng lượng tiêu hao ước tính, kcal"),
        },
    ),
    "Exercise": Label(
        "mixed",
        "bài tập trong catalog",
        {
            "name_vi": _p("str", "tên tiếng Việt"),
            "name_en": _p("str", "tên tiếng Anh"),
            "name_search": _p("str", "tên không dấu, chữ thường; so khớp với $terms"),
            "kind": _p("str", "STRENGTH | ENDURANCE | ..."),
        },
    ),
    "BodyMetric": Label(
        "private",
        "số đo cơ thể",
        {
            **RECORD_TIME,
            "weight_kg": _p("float", "cân nặng, kg"),
            "height_cm": _p("float", "chiều cao, cm"),
            "body_fat_pct": _p("float", "tỷ lệ mỡ, %"),
            "muscle_mass_kg": _p("float", "khối cơ, kg"),
            "origin": _p("str", "MANUAL hoặc nguồn thiết bị"),
        },
    ),
    "Goal": Label(
        "private",
        "mục tiêu (cả đang thực hiện lẫn đã kết thúc)",
        {
            "title": _p("str", "tiêu đề"),
            "goal_types": _p("list", "loại mục tiêu, vd. ['WEIGHT_LOSS']"),
            "weight_kg_target": _p("float", "cân nặng đích, kg"),
            "start_date": _p("date", "ngày bắt đầu"),
            "target_date": _p("date", "hạn"),
            "status": _p("str", "IN_PROGRESS | COMPLETED | CANCELLED ..."),
        },
    ),
    "DailyHealth": Label(
        "private",
        "tổng hợp một ngày từ thiết bị đeo (chỉ khi người dùng đồng ý)",
        {
            "local_date": _p("date", "ngày"),
            "steps": _p("float", "số bước"),
            "distance_m": _p("float", "quãng đường, m"),
            "active_minutes": _p("float", "phút vận động"),
            "total_kcal": _p("float", "tổng năng lượng tiêu hao, kcal"),
            "active_kcal": _p("float", "năng lượng vận động, kcal"),
            "resting_hr_bpm": _p("float", "nhịp tim nghỉ, bpm"),
            "hrv_ms": _p("float", "HRV, ms"),
            "spo2_avg_pct": _p("float", "SpO2 trung bình, %"),
            "sleep_minutes": _p("float", "phút ngủ"),
            "vo2_max": _p("float", "VO2max"),
        },
    ),
    "SleepSession": Label(
        "private",
        "một giấc ngủ từ thiết bị hoặc tự ghi",
        {
            "start_at": _p("datetime", "bắt đầu (UTC)"),
            "end_at": _p("datetime", "kết thúc (UTC)"),
            "local_date": _p("date", "ngày của buổi sáng thức dậy"),
            "is_nap": _p("bool", "giấc ngắn ban ngày"),
            "minutes_asleep": _p("float", "phút ngủ"),
            "minutes_awake": _p("float", "phút thức giấc"),
            "deep_minutes": _p("float", "phút ngủ sâu"),
            "light_minutes": _p("float", "phút ngủ nông"),
            "rem_minutes": _p("float", "phút REM"),
            "efficiency_pct": _p("float", "hiệu quả giấc ngủ, %"),
        },
    ),
    "DeviceWorkout": Label(
        "private",
        "buổi vận động do thiết bị ghi",
        {
            **RECORD_TIME,
            "exercise_type": _p("str", "loại vận động"),
            "display_name": _p("str", "tên hiển thị"),
            "active_min": _p("float", "phút vận động"),
            "distance_km": _p("float", "quãng đường, km"),
            "energy_kcal": _p("float", "năng lượng, kcal"),
            "avg_hr_bpm": _p("float", "nhịp tim trung bình, bpm"),
            "steps": _p("float", "số bước"),
        },
    ),
    "Day": Label(
        "private",
        "tổng hợp một ngày địa phương, giữ lâu dài (bộ nhớ dài hạn)",
        {
            "date": _p("date", "ngày"),
            "meals": _p("int", "số bữa đã ghi"),
            "kcal": _p("float", "kcal đã ăn (null khi không ghi bữa nào)"),
            "protein_g": _p("float", "protein đã ăn, g"),
            "carbohydrate_g": _p("float", "carbohydrate đã ăn, g"),
            "fat_g": _p("float", "chất béo đã ăn, g"),
            "trainings": _p("int", "số buổi tập đã ghi"),
            "training_minutes": _p("float", "phút tập đã ghi"),
            "training_load": _p("float", "tổng tải sRPE"),
            "steps": _p("float", "số bước (thiết bị)"),
            "active_minutes": _p("float", "phút vận động (thiết bị)"),
            "total_kcal": _p("float", "năng lượng tiêu hao (thiết bị), kcal"),
            "resting_hr_bpm": _p("float", "nhịp tim nghỉ (thiết bị)"),
            "hrv_ms": _p("float", "HRV (thiết bị), ms"),
            "sleep_minutes": _p("float", "phút ngủ của đêm kết thúc vào sáng ngày này"),
            "weight_kg": _p("float", "cân nặng cuối cùng trong ngày"),
        },
    ),
    "Period": Label(
        "private",
        "tổng hợp một tuần (thứ Hai-Chủ nhật) hoặc một tháng, giữ lâu dài",
        {
            "grain": _p("str", "'week' | 'month'"),
            "label": _p("str", "vd. '2026-W45' hoặc '2026-11'"),
            "start": _p("date", "ngày đầu kỳ"),
            "end": _p("date", "ngày cuối kỳ"),
            "days_with_meals": _p("int", "số ngày có ghi bữa ăn"),
            "kcal_avg": _p("float", "kcal trung bình mỗi ngày có ghi"),
            "protein_avg": _p("float", "protein trung bình mỗi ngày có ghi, g"),
            "trainings": _p("int", "số buổi tập"),
            "training_minutes": _p("float", "tổng phút tập"),
            "training_load": _p("float", "tổng tải sRPE"),
            "steps_avg": _p("float", "số bước trung bình mỗi ngày có dữ liệu"),
            "sleep_avg_minutes": _p("float", "phút ngủ trung bình mỗi đêm có dữ liệu"),
            "weight_start": _p("float", "cân nặng đầu kỳ"),
            "weight_end": _p("float", "cân nặng cuối kỳ"),
        },
    ),
    "Run": Label(
        "private",
        "một lượt hội thoại: chỉ quyết định có cấu trúc, không có văn bản",
        {
            "at": _p("datetime", "thời điểm (UTC)"),
            "local_date": _p("date", "ngày địa phương"),
            "session_id": _p("str", "phiên; so với $session_id"),
            "intent": _p("str", "ý định, vd. LOG_MEAL, REVIEW_NUTRITION"),
            "intent_label": _p("str", "nhãn tiếng Việt của ý định"),
            "domain": _p("str", "miền"),
            "status": _p("str", "completed | needs_input | pending_confirmation | failed"),
            "decision": _p(
                "str", "approved | rejected | pending | null: người dùng làm gì với thẻ xác nhận"
            ),
            "edited_fields": _p("list", "các trường người dùng sửa trên thẻ"),
            "tools": _p("list", "tool đã chạy"),
        },
    ),
    "Execution": Label(
        "private",
        "một lần gọi tool trong lượt",
        {
            "at": _p("datetime", "thời điểm (UTC)"),
            "tool": _p("str", "tên tool"),
            "domain": _p("str", "miền của tool"),
            "status": _p("str", "succeeded | failed"),
            "args": _p("str", "tham số có cấu trúc đã lưu, 'k=v, ...'"),
            "outcome": _p("str", "kết quả gọn từ backend"),
        },
    ),
    "Intent": Label(
        "shared",
        "loại ý định",
        {
            "name": _p("str", "mã ý định"),
            "label": _p("str", "nhãn tiếng Việt"),
        },
    ),
}

RECORDS = ("Meal", "Training", "BodyMetric", "Goal", "DailyHealth", "SleepSession", "DeviceWorkout")
# (từ, quan hệ, tới, thuộc tính của quan hệ). Mọi quan hệ từ nút riêng tới nút mixed chỉ được projector tạo khi nút đích
# thuộc cùng người dùng hoặc là dữ liệu hệ thống, nên đi qua chúng không chạm dữ liệu của người khác.
RELATIONSHIPS = (
    ("User", "LOGGED", "Meal", {}),
    ("User", "TRAINED", "Training", {}),
    ("User", "HAS_MEASUREMENT", "BodyMetric", {}),
    ("User", "HAS_GOAL", "Goal", {}),
    ("User", "HAS_DAILY_HEALTH", "DailyHealth", {}),
    ("User", "SLEPT", "SleepSession", {}),
    ("User", "WORKED_OUT", "DeviceWorkout", {}),
    ("Meal", "HAS_ITEM", "MealItem", {}),
    ("MealItem", "REFERS_TO", "Food", {}),
    (
        "Training",
        "PERFORMED",
        "Exercise",
        {
            "hard_sets": _p("int", "số hiệp nặng"),
            "volume_kg": _p("float", "khối lượng, kg"),
            "best_e1rm_kg": _p("float", "e1RM tốt nhất của buổi, kg"),
            "distance_km": _p("float", "quãng đường, km"),
            "duration_min": _p("float", "thời lượng, phút"),
        },
    ),
    *((record, "ON_DAY", "Day", {}) for record in RECORDS if record != "Goal"),
    ("Day", "IN", "Period", {}),
    (
        "User",
        "FREQUENTLY_EATS",
        "Food",
        {
            "count": _p("int", "số lần ăn trong 90 ngày"),
            "last_date": _p("str", "lần gần nhất 'YYYY-MM-DD'"),
        },
    ),
    (
        "User",
        "PRACTICES",
        "Exercise",
        {
            "sessions": _p("int", "số buổi có bài này"),
            "last_date": _p("str", "lần gần nhất 'YYYY-MM-DD'"),
            "best_e1rm_kg": _p("float", "e1RM tốt nhất, kg"),
            "distance_km": _p("float", "tổng quãng đường, km"),
        },
    ),
    ("Run", "NEXT", "Run", {}),
    ("Run", "HAS_EXECUTION", "Execution", {}),
    ("Run", "HAS_INTENT", "Intent", {}),
    *(("Run", "ABOUT", record, {}) for record in (*RECORDS, "Food")),
    *(("Execution", "TARGETS", record, {}) for record in (*RECORDS, "Food")),
    ("Meal", "REPLACES", "Meal", {}),
    ("Training", "REPLACES", "Training", {}),
)
REL_TYPES = {rel for _, rel, _, _ in RELATIONSHIPS}
REL_PROPS = {rel: props for _, rel, _, props in RELATIONSHIPS if props}
ENDPOINTS = {(a, rel, b) for a, rel, b, _ in RELATIONSHIPS}
# Lượt và lần thực thi chỉ đọc được trong các phiên còn sống của người dùng (cổng thế hệ phiên SQL).
SESSION_SCOPED = ("Run", "Execution")


# ---------------------------------------------------------------- chuyển đổi giá trị cho projector


def to_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def to_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _number(value, kind):
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        return int(float(value)) if kind == "int" else float(value)
    except (TypeError, ValueError):
        return None


def coerce(prop, value):
    """Một giá trị nguồn thành kiểu Neo4j của thuộc tính; giá trị không hợp lệ thành None."""
    if value is None:
        return None
    if prop.type == "date":
        return to_date(value)
    if prop.type == "datetime":
        return to_datetime(value)
    if prop.type in {"float", "int"}:
        return _number(value, prop.type)
    if prop.type == "bool":
        return bool(value)
    if prop.type == "list":
        return [str(item) for item in value] if isinstance(value, list) else None
    return str(value)


def local_parts(moment):
    if moment is None:
        return None, None
    local = moment.astimezone(LOCAL)
    return local.date(), local.strftime("%H:%M")


# ---------------------------------------------------------------- mô tả lược đồ cho prompt


def describe():
    """Lược đồ gọn cho prompt sinh Cypher: nhãn, thuộc tính có kiểu và quan hệ."""
    lines = ["Nút (thuộc tính: kiểu, ý nghĩa):"]
    for name, label in LABELS.items():
        props = "; ".join(f"{key}: {prop.type}, {prop.desc}" for key, prop in label.props.items())
        lines.append(f"- {name} ({label.desc}) — {props}")
    lines.append("Quan hệ:")
    grouped = {}
    for a, rel, b, props in RELATIONSHIPS:
        grouped.setdefault((rel, tuple(props)), []).append(f"({a})-[:{rel}]->({b})")
    for (rel, props), paths in grouped.items():
        extra = (
            " — thuộc tính: "
            + "; ".join(f"{k}: {v.type}, {v.desc}" for k, v in REL_PROPS[rel].items())
            if props
            else ""
        )
        lines.append("- " + ", ".join(paths) + extra)
    return "\n".join(lines)
