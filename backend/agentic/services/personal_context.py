"""Ngữ cảnh cá nhân cho yêu cầu tư vấn và phân tích; do code quyết định, không bao giờ do model chọn.

Một câu hỏi tư vấn về người dùng ("với thể lực hiện tại của tôi", "kế hoạch hợp với tôi") được
trả lời từ dữ liệu đã lưu của người dùng cộng tri thức đã kiểm chứng, không phải bằng cách hỏi người dùng
những dữ kiện HercFit đã có. Module này cung cấp:

* thẻ ngữ cảnh người dùng: GET /api/assistant/context, dựng gọn cho prompt;
* phát hiện yêu cầu tư vấn/phân tích cá nhân và chủ đề của chúng;
* các lần đọc sâu (tool phân tích của backend) mỗi chủ đề cần trước khi tra cứu hoặc trả lời;
* một mô tả truy hồi chỉ dùng nội bộ để cơ sở tri thức được tìm theo trình độ của người dùng;
* các ô thông tin thẻ đã trả lời, dùng để bỏ câu hỏi làm rõ về chúng.
"""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from agentic.observability import annotate
from domains.catalog.models.foods import normalize_food_text

CONTEXT_PATH = "/api/assistant/context"
CARD_KEYS = frozenset(
    {"today", "profile", "body", "athlete", "running", "training_4w", "inventory"}
)
TIMEZONE = "Asia/Ho_Chi_Minh"
TOPICS = (
    "running",
    "strength",
    "training",
    "nutrition",
    "body",
    "recovery",
    "wellbeing",
    "general",
)

# Cách diễn đạt khiến yêu cầu nói về chính người dùng này (không dấu, chữ thường).
FIRST_PERSON = re.compile(
    r"\b(?:toi|minh|tui|em|ban than|cua toi|cua minh)\b|the trang|hien tai|trinh do|phu hop voi|"
    r"\bmy\b|\bme\b|\bi(?:'m| am| have| run| want| need| should| can| do)\b|current (?:fitness|level|pace)"
)
# Tư vấn, lập kế hoạch hay phân tích chứ không phải định nghĩa hay một mục nhật ký.
ADVICE = re.compile(
    r"lam sao|lam the nao|\bnen\b|co nen|giup|ke hoach|lich tap|giao an|cai thien|\btang\b|\bgiam\b|\bkeo\b|"
    r"dat duoc|muc tieu|phan tich|danh gia|nhan xet|tien bo|phu hop|bao lau|the nao|tu van|loi khuyen|"
    r"qua suc|co dang|co on|du chua|co du|co tot|"
    r"how (?:do|can|should|to)|should i|plan|improve|advice|analy|review|progress|reach|goal|am i|enough"
)
TOPIC_WORDS = {
    "running": r"\bchay\b|\bpace\b|\b(?:5|10|21|42)k\b|marathon|km/tuan|\brun(?:ning|ner)?\b|\bjog|tempo|interval|sai chan",
    "strength": r"\bgym\b|\bta\b|squat|deadlift|bench|\b1rm\b|e1rm|tang co|co bap|strength|hypertroph|\blift",
    "nutrition": r"\ban\b|\ban uong\b|calo|kcal|protein|\bdam\b|carb|tinh bot|chat beo|dinh duong|\bbua\b|macro|nutrition|diet|meal",
    "body": r"can nang|giam can|tang can|\bmo\b|\bbmi\b|vong eo|weight|body fat|\bfat\b",
    "recovery": r"\bngu\b|giac ngu|phuc hoi|nhip tim nghi|\bhrv\b|met moi|qua tai|sleep|recover|fatigue|overtrain",
}
DOMAIN_TOPICS = {
    "coaching": "training",
    "trainings": "training",
    "training_plans": "training",
    "progress": "nutrition",
    "meals": "nutrition",
    "foods": "nutrition",
    "metrics": "body",
    "goals": "body",
    "profile": "body",
    "health": "recovery",
    "exercises": "training",
}
# Yêu cầu ghi hoặc tra một mục catalog không bao giờ là "tư vấn", dù diễn đạt thế nào.
NON_ADVICE_INTENTS = {
    "LOG_FOOD",
    "LOG_EXERCISE",
    "catalog_lookup",
    "catalog_research",
    "catalog_estimate",
    "PROFILE_UPDATE",
}
# Các tuyến xem lại chỉ đọc: một câu hỏi tư vấn ở đó ("cân nặng của tôi chạy marathon được không?") đi theo
# đường ngữ cảnh cá nhân để câu trả lời cũng có tri thức. Các tuyến lập kế hoạch, ghi nhật ký và mục tiêu có thể
# ghi và vẫn là tuyến tool.
REVIEW_DOMAINS = {"coaching", "metrics", "progress", "health", "profile"}


def today() -> date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def is_personal_advice(text: str) -> bool:
    words = normalize_food_text(text or "")
    return bool(FIRST_PERSON.search(words) and ADVICE.search(words))


# Môn thể thao và thuật ngữ khoa học vận động ngoài TOPIC_WORDS (không dấu); "boi" (bởi) không dùng một mình.
SPORT_TERMS = (
    r"the thao|tap luyen|the duc|the hinh|the luc|suc ben|suc manh|khoi dong|gian co|keo gian|nhip tim|"
    r"bong da|cau long|bong ro|bong chuyen|boi loi|dap xe|leo nui|vo2 ?max|lactate|lactic|glycogen|creatine|"
    r"whey|bcaa|dien giai|electrolyte|cardio|hiit|aerobic|anaerobic|crossfit|calisthenics|yoga|pilates|"
    r"triathlon|trail|tennis|football|soccer|basketball|cycling|swim|workout|exercise|stretch|warm.?up"
)
# Cách hỏi kiến thức (không dấu): khác với trò chuyện, kể lại hay cảm ơn.
QUESTION_WORDS = re.compile(
    r"\b(?:gi|nen|co phai|duoc khong|hay khong|nhu the nao|the nao|lam sao|tai sao|vi sao|bao nhieu|bao lau|khi nao|co nen|"
    r"co tot|co hai|co loi|co can|khac nhau|khac gi|anh huong|tac dung|loi ich|"
    r"what|why|how|when|which|should|does|difference)\b"
)
KNOWLEDGE_TOPIC = re.compile("|".join([*TOPIC_WORDS.values(), SPORT_TERMS]))


def knowledge_question(text: str) -> bool:
    """Một câu hỏi kiến thức về thể thao, dinh dưỡng hay cơ thể: lưới an toàn khi router gọi nó là trò chuyện."""
    words = normalize_food_text(text or "")
    return bool(QUESTION_WORDS.search(words) and KNOWLEDGE_TOPIC.search(words))


def topic_for(text: str, domain: str | None = None) -> str:
    words = normalize_food_text(text or "")
    scores = {topic: len(re.findall(pattern, words)) for topic, pattern in TOPIC_WORDS.items()}
    best = max(scores, key=lambda topic: scores[topic])
    if scores[best]:
        return best
    return DOMAIN_TOPICS.get(domain or "", "general")


def wants_personal_context(text: str, decision: dict) -> bool:
    """Cờ của router, hoặc tư vấn cá nhân do code phát hiện, ngoài các luồng ghi/catalog."""
    if decision.get("read_only") or decision.get("intent") in NON_ADVICE_INTENTS:
        return False
    action = decision.get("action")
    if action in {"research", "answer", "clarify"}:
        return bool(decision.get("personalize")) or is_personal_advice(text)
    if action == "tool" and decision.get("domain") in REVIEW_DOMAINS:
        return is_personal_advice(text)
    return False


def _range(days: int, end: date) -> dict:
    return {
        "start_date": (end - timedelta(days=days - 1)).isoformat(),
        "end_date": end.isoformat(),
        "timezone": TIMEZONE,
    }


def deep_reads(topic: str, end: date | None = None) -> list[tuple[str, dict]]:
    """Các phân tích backend mỗi chủ đề cần ngoài thẻ; mọi giá trị đều do backend tính."""
    end = end or today()
    profile = ("get_training_profile", {})
    insights = ("get_training_insights", {"timezone": TIMEZONE})
    return {
        "running": [
            profile,
            ("get_running_summary", _range(56, end)),
            ("get_training_load", _range(7, end)),
            insights,
        ],
        "strength": [
            profile,
            ("get_strength_records", {"timezone": TIMEZONE}),
            ("get_training_summary", _range(56, end)),
            insights,
        ],
        "training": [profile, ("get_training_summary", _range(56, end)), insights],
        "nutrition": [
            ("get_nutrition_targets", {"timezone": TIMEZONE}),
            ("get_progress", _range(14, end)),
            ("current_goal", {}),
        ],
        "body": [("get_progress", _range(28, end)), ("current_goal", {}), ("latest_metrics", {})],
        "recovery": [
            ("get_health_overview", {"days": 28, "timezone": TIMEZONE}),
            ("get_training_load", _range(7, end)),
        ],
        # Chất lượng sống (chế độ Plan): giấc ngủ, vận động, phục hồi từ thiết bị cùng ăn uống, cơ thể và tải tập.
        "wellbeing": [
            ("get_health_overview", {"days": 28, "timezone": TIMEZONE}),
            ("get_progress", _range(28, end)),
            ("latest_metrics", {}),
            ("current_goal", {}),
            ("get_training_load", _range(7, end)),
        ],
    }.get(topic, [])


async def load_card(backend, token) -> dict | None:
    """Thẻ ngữ cảnh của người dùng; lượt vẫn tiếp tục khi backend không dựng được thẻ."""
    try:
        card = await backend.request("GET", CONTEXT_PATH, token, params={"timezone": TIMEZONE})
    except Exception as exc:
        annotate(user_context="unavailable", user_context_error=type(exc).__name__)
        return None
    if not isinstance(card, dict) or not CARD_KEYS <= card.keys():
        # Dạng dữ liệu bất ngờ (backend cũ hơn, trang lỗi của proxy) được coi như không có thẻ.
        annotate(user_context="invalid")
        return None
    annotate(user_context="loaded", user_context_missing=len(card.get("missing") or []))
    return card


# ---------------------------------------------------------------- dựng hiển thị


def pace(seconds) -> str | None:
    if not seconds:
        return None
    seconds = round(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}/km"


def duration(seconds) -> str | None:
    if not seconds:
        return None
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


LEVELS = {"BEGINNER": "mới tập", "INTERMEDIATE": "trung bình", "ADVANCED": "nâng cao"}
FOCUS = {"RUNNING": "chạy bộ", "STRENGTH": "sức mạnh", "HYBRID": "kết hợp"}
MISSING = {
    "age": "tuổi",
    "sex": "giới tính",
    "weight": "cân nặng",
    "height": "chiều cao",
    "goal": "mục tiêu",
    "athlete_profile": "hồ sơ VĐV",
    "recent_race": "thành tích chạy gần đây",
    "running_history": "lịch sử chạy",
    "max_hr": "nhịp tim tối đa",
}


def _join(parts) -> str:
    return ", ".join(part for part in parts if part)


def render_card(card: dict | None) -> str | None:
    """Bản tóm tắt tiếng Việt gọn (vài trăm token) có ngày tháng; là dữ liệu, không phải chỉ dẫn."""
    if not card:
        return None
    profile, body, goal, athlete = card["profile"], card["body"], card.get("goal"), card["athlete"]
    running, training, inventory = card["running"], card["training_4w"], card["inventory"]
    lines = [
        f"Hồ sơ người dùng HercFit (dữ liệu đã lưu, tính đến {card['today']}; dùng để cá nhân hoá, không hỏi lại):"
    ]
    lines.append(
        "- Cơ bản: "
        + (
            _join(
                [
                    f"{profile['age']} tuổi" if profile.get("age") else None,
                    {"MALE": "nam", "FEMALE": "nữ"}.get(profile.get("sex") or ""),
                    f"cân nặng {body['weight_kg']} kg" if body.get("weight_kg") else None,
                    f"cao {body['height_cm']} cm" if body.get("height_cm") else None,
                    f"mỡ {body['body_fat_pct']}%" if body.get("body_fat_pct") else None,
                    f"đo ngày {body['measured_at'][:10]}" if body.get("measured_at") else None,
                ]
            )
            or "chưa có"
        )
    )
    if goal:
        lines.append(
            f"- Mục tiêu hiện tại: {goal['title']}"
            + (f" (đến {goal['target_date']})" if goal.get("target_date") else "")
        )
    if athlete.get("configured"):
        race = athlete.get("recent_race") or {}
        lines.append(
            "- Hồ sơ VĐV: "
            + _join(
                [
                    f"trình độ {LEVELS.get(athlete['experience_level'], athlete['experience_level'])}",
                    f"trọng tâm {FOCUS.get(athlete['primary_focus'], athlete['primary_focus'])}",
                    f"{athlete['available_days']} buổi/tuần × {athlete['session_minutes']} phút",
                    "chấn thương khai báo: "
                    + (", ".join(athlete["injuries"]) if athlete.get("injuries") else "không"),
                    f"HRmax {athlete['max_hr']}" if athlete.get("max_hr") else None,
                    f"HR nghỉ {athlete['resting_hr']}" if athlete.get("resting_hr") else None,
                    f"pace ngưỡng {pace(athlete['threshold_pace_s_per_km'])}"
                    if athlete.get("threshold_pace_s_per_km")
                    else None,
                    f"thành tích gần đây {race.get('distance_meters', 0) / 1000:g} km trong {duration(race.get('time_seconds'))}"
                    if race.get("time_seconds")
                    else None,
                ]
            )
        )
    if running.get("runs"):
        last = running.get("last_run") or {}
        efforts = running.get("best_efforts") or {}
        predictions = running.get("race_predictions_seconds") or {}
        lines.append(
            "- Chạy bộ "
            + str(running["window_weeks"])
            + " tuần: "
            + _join(
                [
                    f"{running['runs']} buổi ({running['weeks_with_runs']} tuần có chạy)",
                    f"4 tuần gần nhất TB {running['avg_weekly_km_4w']} km/tuần, {running['avg_weekly_runs_4w']} buổi/tuần"
                    if running.get("avg_weekly_km_4w") is not None
                    else None,
                    f"pace TB {pace(running['avg_pace_s_per_km_4w'])}"
                    if running.get("avg_pace_s_per_km_4w")
                    else None,
                    f"dài nhất {running['longest_run_km']} km"
                    if running.get("longest_run_km")
                    else None,
                    f"tỉ lệ chạy nhẹ {running['easy_share_pct']}%"
                    if running.get("easy_share_pct") is not None
                    else None,
                ]
            )
        )
        if last:
            lines.append(
                f"  Buổi gần nhất {last['date']}: "
                + _join(
                    [
                        f"{last['distance_km']} km" if last.get("distance_km") else None,
                        pace(last.get("pace_s_per_km")),
                        last.get("workout_type"),
                    ]
                )
            )
        if efforts:
            lines.append(
                "  Thành tích tốt nhất: "
                + _join(
                    f"{label} {duration(item['time_seconds'])} ({item['date']})"
                    for label, item in efforts.items()
                )
            )
        if predictions:
            lines.append(
                "  Dự đoán: "
                + _join(f"{label} {duration(value)}" for label, value in predictions.items())
            )
    if training.get("sessions"):
        by = training.get("sessions_by_discipline") or {}
        lines.append(
            "- Tập 4 tuần: "
            + _join(
                [
                    f"{training['sessions']} buổi ("
                    + _join(f"{key} {value}" for key, value in by.items())
                    + ")",
                    f"ACWR hôm nay {training['acwr']}"
                    if training.get("acwr") is not None
                    else None,
                ]
            )
        )
    lines.append(
        "- Dữ liệu có sẵn: "
        + _join(
            [
                f"{inventory['trainings_60d']} buổi tập/60 ngày",
                f"{inventory['body_metrics']} lần đo cơ thể",
                f"{inventory['meals_14d']} bữa ăn/14 ngày",
                "Google Health: "
                + (
                    "đã kết nối, cho phép trợ lý dùng"
                    if inventory.get("health_shared_with_assistant")
                    else "đã kết nối, chưa cho phép trợ lý"
                    if inventory.get("health_connected")
                    else "chưa kết nối"
                ),
            ]
        )
    )
    if card.get("missing"):
        lines.append(
            "- Chưa có dữ liệu: "
            + ", ".join(MISSING.get(name, name) for name in card["missing"])
            + " (chỉ hỏi những mục này khi thật sự cần)"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------- truy hồi


def retrieval_descriptor(card: dict | None, topic: str) -> str | None:
    """Mô tả vận động viên ở mức thô, chỉ thêm vào lần tìm trong cơ sở tri thức nội bộ (không bao giờ web):
    những đoạn một huấn luyện viên sẽ đọc cho trình độ này, không phải cho vận động viên đỉnh cao."""
    if not card:
        return None
    athlete, running = card["athlete"], card["running"]
    level = {"BEGINNER": "novice", "INTERMEDIATE": "intermediate", "ADVANCED": "advanced"}.get(
        athlete.get("experience_level"), "recreational"
    )
    if topic in {"running", "training", "recovery"} and running.get("runs"):
        parts = [f"{level} recreational runner"]
        if running.get("avg_weekly_km_4w"):
            parts.append(f"about {5 * round(running['avg_weekly_km_4w'] / 5) or 5} km per week")
        if running.get("avg_weekly_runs_4w"):
            parts.append(f"{round(running['avg_weekly_runs_4w'])} runs per week")
        if running.get("avg_pace_s_per_km_4w"):
            parts.append(
                f"easy pace around {pace(15 * round(running['avg_pace_s_per_km_4w'] / 15))}"
            )
        five = (running.get("best_efforts") or {}).get("5K") or {}
        if five.get("time_seconds"):
            parts.append(f"5 km in about {duration(30 * round(five['time_seconds'] / 30))}")
        return (
            "Training guidance for an " + ", ".join(parts)
            if level[0] in "aeiou"
            else "Training guidance for a " + ", ".join(parts)
        )
    if topic == "strength":
        return f"Strength training guidance for {'an' if level[0] in 'aeiou' else 'a'} {level} lifter training {athlete.get('available_days', 3)} days per week"
    if topic == "wellbeing":
        return (
            f"Sleep, recovery, daily activity and nutrition habits for {'an' if level[0] in 'aeiou' else 'a'} "
            f"{level} recreational athlete"
        )
    if topic in {"nutrition", "body"}:
        return f"Nutrition and body composition guidance for {'an' if level[0] in 'aeiou' else 'a'} {level} recreational athlete"
    return None


# ---------------------------------------------------------------- làm rõ


def _known(card, *paths):
    for path in paths:
        value = card
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value not in (None, [], {}, 0, False):
            return True
    return False


# Cách diễn đạt câu hỏi → thẻ đã trả lời nó chưa.
SLOTS = {
    "age": (r"tuoi|\bage\b", ("profile.age",)),
    "weight": (r"can nang|\bweight\b|bao nhieu kg", ("body.weight_kg",)),
    "height": (r"chieu cao|\bheight\b|cao bao nhieu", ("body.height_cm",)),
    "sex": (r"gioi tinh|\bsex\b|\bgender\b", ("profile.sex",)),
    "experience": (r"kinh nghiem|bao lau|trinh do|experience|how long", ("athlete.configured",)),
    "volume": (
        r"km\s*/\s*tuan|km moi tuan|bao nhieu km|so buoi|buoi\s*/\s*tuan|may buoi|weekly|per week",
        ("running.runs", "training_4w.sessions"),
    ),
    "recent_run": (
        r"gan nhat|gan day|pace hien tai|thanh tich|\bpb\b|recent|personal best",
        ("running.last_run", "running.best_efforts", "athlete.recent_race"),
    ),
    "injuries": (r"chan thuong|benh ly|tien su|injur", ("athlete.configured",)),
    "schedule": (
        r"may ngay|ngay nao|so ngay|lich ranh|thoi gian tap|available",
        ("athlete.configured",),
    ),
    "goal": (r"muc tieu|\bgoal\b", ("goal",)),
    "max_hr": (r"nhip tim toi da|max hr|hrmax", ("athlete.max_hr",)),
}


def answered_by_card(question: str, card: dict | None) -> bool:
    """True khi mọi dữ kiện câu hỏi hỏi tới đã có trong thẻ."""
    if not card:
        return False
    words = normalize_food_text(question or "")
    asked = [paths for pattern, paths in SLOTS.values() if re.search(pattern, words)]
    return bool(asked) and all(_known(card, *paths) for paths in asked)


def unanswered(questions: list[dict], card: dict | None) -> list[dict]:
    kept = [
        q
        for q in questions
        if not answered_by_card(q.get("label", "") + " " + q.get("question", ""), card)
    ]
    if len(kept) != len(questions):
        annotate(clarification_dropped=len(questions) - len(kept))
    return kept
