"""Phép chiếu có bảo vệ theo phiên bản. Mỗi sự kiện là một transaction Neo4j nguyên tử."""

import calendar
import json
from datetime import datetime, timedelta, timezone

from .driver import value
from .intents import INTENTS
from .intents import hub as intent_hub
from .intents import label as intent_label
from .model import LOCAL, MODEL_VERSION, build_user_model, model_links
from .models import ProjectionEvent
from .schema import LABELS, REL_PROPS, coerce, local_parts, to_date, to_datetime
from .service import normalize

# v5: thuộc tính có kiểu cho Cypher sinh ra, cây thời gian Day/Period, Run-[:NEXT]->Run, mục tiêu đã kết thúc giữ lại.
PROJECTION_VERSION = 5
NUTRIENTS = {"energy_kcal", "protein_g", "carbohydrate_g", "fat_g", "fiber_g"}
FOOD_FIELDS = NUTRIENTS | {
    "id",
    "version_id",
    "code",
    "name_vi",
    "name_en",
    "category_vi",
    "category_en",
    "item_type",
    "source_type",
    "serving_size",
    "serving_unit",
}
FIELDS = {
    "User": {"id", "is_active", "age", "sex", "activity_level", "training_profile"},
    "Goal": {
        "id",
        "version_id",
        "title",
        "description",
        "goal_types",
        "weight_kg_target",
        "targets",
        "start_date",
        "target_date",
        "status",
    },
    "BodyMetric": {
        "id",
        "version_id",
        "recorded_at",
        "weight_kg",
        "height_cm",
        "body_fat_pct",
        "muscle_mass_kg",
        "source",
    },
    "Food": FOOD_FIELDS,
    "Meal": NUTRIENTS
    | {
        "id",
        "version_id",
        "name",
        "consumed_at",
        "timezone",
        "detail_status",
        "replaces_id",
        "nutrition_incomplete",
    },
    "Training": {
        "id",
        "version_id",
        "name",
        "started_at",
        "timezone",
        "detail_status",
        "discipline",
        "duration_seconds",
        "session_rpe",
        "training_load",
        "energy_kcal",
        "calories_incomplete",
        "replaces_id",
    },
    "Execution": {
        "run_id",
        "session_id",
        "session_generation",
        "tool",
        "status",
        "duration_ms",
        "error_code",
        "template_id",
        "template_version",
        "occurred_at",
        # Bộ nhớ quyết định: tham số có cấu trúc đã lọc (tools.registry.remembered_args) và kết quả gọn từ backend.
        "args",
        "outcome",
    },
    "Session": {"session_id", "generation"},
    # Một lượt hội thoại: chỉ dữ kiện định tuyến có cấu trúc, không bao giờ có văn bản tin nhắn hay câu trả lời.
    "Run": {
        "run_id",
        "session_id",
        "session_generation",
        "intent",
        "domain",
        "action",
        "status",
        "tools",
        "occurred_at",
        "prev_run_id",
        "decision",
        "edited_fields",
    },
    # Dữ liệu thiết bị đeo mà người dùng cho phép trợ lý dùng: chỉ tổng hợp ngày và các phiên.
    "DailyHealth": {
        "id",
        "version_id",
        "local_date",
        "source",
        "steps",
        "distance_m",
        "floors",
        "active_minutes",
        "active_zone_minutes",
        "total_kcal",
        "active_kcal",
        "resting_hr_bpm",
        "hr_avg_bpm",
        "hrv_ms",
        "spo2_avg_pct",
        "respiratory_rate",
        "vo2_max",
        "hydration_ml",
        "sleep_minutes",
    },
    "SleepSession": {
        "id",
        "version_id",
        "source",
        "start_at",
        "end_at",
        "local_date",
        "is_main",
        "is_nap",
        "minutes_asleep",
        "minutes_awake",
        "minutes_in_period",
        "deep_minutes",
        "light_minutes",
        "rem_minutes",
        "efficiency_pct",
    },
    "DeviceWorkout": {
        "id",
        "version_id",
        "source",
        "started_at",
        "ended_at",
        "local_date",
        "exercise_type",
        "display_name",
        "active_seconds",
        "energy_kcal",
        "distance_m",
        "steps",
        "avg_hr_bpm",
        "active_zone_minutes",
    },
}
HEALTH_KINDS = ("DailyHealth", "SleepSession", "DeviceWorkout")
PROFILE_FIELDS = {
    "experience_level",
    "primary_focus",
    "available_days",
    "session_minutes",
    "equipment",
}
TURN_STATUSES = {"completed", "needs_input", "pending_confirmation", "failed"}
MODEL_SOURCES = {"User", "Goal", "BodyMetric", "Meal", "Training", *HEALTH_KINDS}
ITEM_FIELDS = NUTRIENTS | {
    "id",
    "version_id",
    "position",
    "food_id",
    "quantity",
    "unit",
    "nutrition_incomplete",
}
TRAINING_ITEM_FIELDS = {
    "id",
    "position",
    "exercise_id",
    "kind",
    "duration_seconds",
    "distance_meters",
    "volume_kg",
    "best_e1rm_kg",
    "hard_sets",
    "energy_kcal",
}
EXERCISE_FIELDS = {"id", "code", "name_vi", "name_en", "kind", "source_type"}
RELATIONS = {
    "Goal": "HAS_GOAL",
    "BodyMetric": "HAS_MEASUREMENT",
    "Meal": "LOGGED",
    "Training": "TRAINED",
    "DailyHealth": "HAS_DAILY_HEALTH",
    "SleepSession": "SLEPT",
    "DeviceWorkout": "WORKED_OUT",
}
# Các loại bản ghi mà một lượt hội thoại có thể nói VỀ (và một lần thực thi có thể NHẮM TỚI).
RECORD_KINDS = {"Goal", "BodyMetric", "Meal", "Food", "Training", *HEALTH_KINDS}
# Bản ghi có ngày địa phương: nối -[:ON_DAY]->(Day) và nuôi tổng hợp ngày/tuần/tháng.
DAY_KINDS = ("Meal", "Training", "BodyMetric", *HEALTH_KINDS)
# Trường thời điểm nguồn của thuộc tính `at`.
SOURCE_TIME = {
    "Meal": "consumed_at",
    "Training": "started_at",
    "BodyMetric": "recorded_at",
    "DeviceWorkout": "started_at",
    "Run": "occurred_at",
    "Execution": "occurred_at",
}


def _ratio(value, divisor):
    try:
        return float(value) / divisor if value is not None else None
    except (TypeError, ValueError):
        return None


def typed_properties(kind, data, occurred_at=None):
    """Thuộc tính có kiểu (schema.LABELS) mà Cypher sinh ra đọc được; tên nguồn khác được đổi hoặc suy ra ở đây."""
    label = LABELS.get(kind)
    if label is None:
        return {}
    source = dict(data)
    if kind == "BodyMetric":
        source["origin"] = data.get("source") or "MANUAL"
    elif kind == "Training":
        source["duration_min"] = _ratio(data.get("duration_seconds"), 60)
    elif kind == "DeviceWorkout":
        source["active_min"] = _ratio(data.get("active_seconds"), 60)
        source["distance_km"] = _ratio(data.get("distance_m"), 1000)
    elif kind == "Food":
        source["name_search"] = normalize(
            " ".join(filter(None, [data.get("name_vi"), data.get("name_en")]))
        )
    elif kind == "Run":
        source["intent_label"] = intent_label(data.get("intent"))
    elif kind == "Execution":
        source["domain"] = tool_domain(data.get("tool", ""))
    if kind in SOURCE_TIME:
        moment = to_datetime(data.get(SOURCE_TIME[kind]) or occurred_at)
        day, clock = local_parts(moment)
        source["at"] = moment
        source.setdefault("local_time", clock)
        if not data.get("local_date"):
            source["local_date"] = day
    typed = {}
    for name, prop in label.props.items():
        converted = coerce(prop, source.get(name))
        if converted is not None:
            typed[name] = converted
    return typed


def _week(day):
    start = day - timedelta(days=day.weekday())
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}", start, start + timedelta(days=6)


def _month(day):
    start = day.replace(day=1)
    return (
        f"{day.year}-{day.month:02d}",
        start,
        day.replace(day=calendar.monthrange(day.year, day.month)[1]),
    )


# Tổng hợp một ngày được tính lại toàn phần từ các bản ghi của ngày đó (sự kiện trùng hay đảo thứ tự vẫn cho cùng
# kết quả). Bản ghi đã quá hạn lưu (pruned) vẫn được tính: tổng hợp là bộ nhớ dài hạn, bản ghi thô thì không.
DAY_ROLLUP = """
MERGE (d:KGEntity {key:$key}) ON CREATE SET d.source_version=0
SET d:Day, d.kind='Day', d.owner_id=$owner, d.scope='PRIVATE', d.deleted=false, d.date=$date
WITH d
CALL (d) {
  OPTIONAL MATCH (m:Meal {owner_id:$owner, local_date:$date}) WHERE m.deleted=false OR m.pruned=true
  RETURN count(m) AS meals, sum(m.energy_kcal) AS kcal, sum(m.protein_g) AS protein,
         sum(m.carbohydrate_g) AS carb, sum(m.fat_g) AS fat
}
CALL (d) {
  OPTIONAL MATCH (t:Training {owner_id:$owner, local_date:$date}) WHERE t.deleted=false OR t.pruned=true
  RETURN count(t) AS trainings, sum(t.duration_min) AS minutes, sum(t.training_load) AS load
}
CALL (d) {
  OPTIONAL MATCH (h:DailyHealth {owner_id:$owner, local_date:$date}) WHERE h.deleted=false OR h.pruned=true
  RETURN max(h.steps) AS steps, max(h.active_minutes) AS active, max(h.total_kcal) AS burned,
         max(h.resting_hr_bpm) AS rhr, max(h.hrv_ms) AS hrv, max(h.sleep_minutes) AS device_sleep
}
CALL (d) {
  OPTIONAL MATCH (s:SleepSession {owner_id:$owner, local_date:$date})
  WHERE (s.deleted=false OR s.pruned=true) AND coalesce(s.is_nap, false) = false
  RETURN count(s) AS sleeps, sum(s.minutes_asleep) AS slept
}
CALL (d) {
  OPTIONAL MATCH (b:BodyMetric {owner_id:$owner, local_date:$date})
  WHERE (b.deleted=false OR b.pruned=true) AND b.weight_kg IS NOT NULL
  WITH b ORDER BY b.at DESC
  RETURN head(collect(b.weight_kg)) AS weight
}
SET d.meals=meals, d.kcal=CASE WHEN meals > 0 THEN round(kcal, 1) END,
    d.protein_g=CASE WHEN meals > 0 THEN round(protein, 1) END,
    d.carbohydrate_g=CASE WHEN meals > 0 THEN round(carb, 1) END,
    d.fat_g=CASE WHEN meals > 0 THEN round(fat, 1) END,
    d.trainings=trainings, d.training_minutes=CASE WHEN trainings > 0 THEN round(minutes, 1) END,
    d.training_load=CASE WHEN trainings > 0 THEN round(load, 1) END,
    d.steps=steps, d.active_minutes=active, d.total_kcal=burned, d.resting_hr_bpm=rhr, d.hrv_ms=hrv,
    d.sleep_minutes=CASE WHEN sleeps > 0 THEN slept ELSE device_sleep END, d.weight_kg=weight
WITH d
CALL (d) {
  MATCH (r:KGEntity {owner_id:$owner})
  WHERE r.kind IN $kinds AND r.local_date = $date AND (r.deleted=false OR r.pruned=true)
  MERGE (r)-[:ON_DAY]->(d)
}
"""
PERIOD_ROLLUP = """
MATCH (d:Day {key:$day_key})
MERGE (p:KGEntity {key:$key}) ON CREATE SET p.source_version=0
SET p:Period, p.kind='Period', p.owner_id=$owner, p.scope='PRIVATE', p.deleted=false,
    p.grain=$grain, p.label=$label, p.start=$start, p.end=$end
MERGE (d)-[:IN]->(p)
WITH p
MATCH (x:Day {owner_id:$owner}) WHERE x.date >= $start AND x.date <= $end
WITH p, x ORDER BY x.date
WITH p, sum(CASE WHEN x.meals > 0 THEN 1 ELSE 0 END) AS days_with_meals,
     avg(CASE WHEN x.meals > 0 THEN x.kcal END) AS kcal, avg(CASE WHEN x.meals > 0 THEN x.protein_g END) AS protein,
     sum(x.trainings) AS trainings, sum(x.training_minutes) AS minutes, sum(x.training_load) AS load,
     avg(x.steps) AS steps, avg(x.sleep_minutes) AS sleep, [w IN collect(x.weight_kg) WHERE w IS NOT NULL] AS weights
SET p.days_with_meals=days_with_meals, p.kcal_avg=round(kcal, 1), p.protein_avg=round(protein, 1),
    p.trainings=trainings, p.training_minutes=round(minutes, 1), p.training_load=round(load, 1),
    p.steps_avg=round(steps), p.sleep_avg_minutes=round(sleep), p.weight_start=head(weights),
    p.weight_end=last(weights)
"""


def sanitize(event):
    payload = event.payload
    data = {key: payload[key] for key in FIELDS[event.aggregate_type] if key in payload}
    if event.aggregate_type == "Meal":
        data["items"] = []
        for source in payload.get("items", []):
            if source.get("is_active", True) is False:
                continue
            item = {key: source[key] for key in ITEM_FIELDS if key in source}
            item["food_snapshot"] = {
                key: val
                for key, val in source.get("food_snapshot", {}).items()
                if key in FOOD_FIELDS
            }
            data["items"].append(item)
    if event.aggregate_type == "Training":
        data["items"] = [
            {
                **{key: source[key] for key in TRAINING_ITEM_FIELDS if key in source},
                "exercise": {
                    key: val
                    for key, val in source.get("exercise_snapshot", {}).items()
                    if key in EXERCISE_FIELDS
                },
            }
            for source in payload.get("items", [])
            if source.get("is_active", True) is not False
        ]
    if event.aggregate_type == "User":
        profile = payload.get("training_profile") or {}
        data["training_profile"] = (
            {key: val for key, val in profile.items() if key in PROFILE_FIELDS}
            if isinstance(profile, dict)
            else {}
        )
    if event.aggregate_type == "Run":
        data["intent"] = data.get("intent") if data.get("intent") in INTENTS else "CHAT"
        data["tools"] = [str(tool) for tool in data.get("tools") or []][:8]
    if event.aggregate_type in {"Execution", "Run"}:
        data["resource_refs"] = [
            {"kind": ref["kind"], "source_id": str(ref["source_id"])}
            for ref in payload.get("resource_refs", [])
            if ref.get("kind") in RECORD_KINDS and ref.get("source_id")
        ][:20]
    return data


def utc_string(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def event_properties(event):
    data = sanitize(event)
    source_at = utc_string(event.occurred_at)
    fact = dict(
        kind=event.aggregate_type,
        source=event.source,
        source_id=event.aggregate_id,
        source_version=event.aggregate_version,
        source_at=source_at,
        data=data,
    )
    props = dict(
        key=event.key,
        kind=event.aggregate_type,
        source=event.source,
        source_id=event.aggregate_id,
        source_version=event.aggregate_version,
        owner_id=event.owner_id,
        scope="SYSTEM" if event.aggregate_type == "Food" and event.owner_id is None else "PRIVATE",
        projection_version=PROJECTION_VERSION,
        source_at=source_at,
        projected_at=datetime.now(timezone.utc).isoformat(),
        deleted=event.operation == "delete",
        fact_json=json.dumps(fact, ensure_ascii=False, separators=(",", ":")),
        search_text=search_text(data),
    )
    # Giấc ngủ thuộc về buổi sáng nó kết thúc; tổng hợp ngày thuộc về ngày địa phương của nó.
    props["business_at"] = utc_string(
        data.get("consumed_at")
        or data.get("recorded_at")
        or data.get("started_at")
        or data.get("end_at")
        or data.get("local_date")
        or data.get("occurred_at")
        or event.occurred_at
    )
    props.update(typed_properties(event.aggregate_type, data, event.occurred_at))
    if event.aggregate_type == "Run" and data.get("prev_run_id"):
        props["prev_key"] = "agent:Run:" + str(data["prev_run_id"])
    if event.aggregate_type == "Goal":
        props["status"] = str(data.get("status", "")).upper()
    if event.aggregate_type == "Execution":
        props.update(
            {key: data.get(key) for key in ("session_id", "session_generation", "run_id", "tool")}
        )
        props["domain"] = tool_domain(data.get("tool", ""))
    if event.aggregate_type == "Run":
        props.update(
            {
                key: data.get(key)
                for key in (
                    "session_id",
                    "session_generation",
                    "run_id",
                    "intent",
                    "domain",
                    "status",
                )
            }
        )
    return props, data


def search_text(data):
    # Bữa ăn và buổi tập được tìm theo những gì đã ăn hoặc đã tập, không chỉ theo "Bữa tối".
    names = [
        data.get(key)
        for key in ("name", "name_vi", "name_en", "title", "display_name", "exercise_type")
    ]
    for item in data.get("items", []):
        snapshot = item.get("food_snapshot") or item.get("exercise") or {}
        names += [snapshot.get("name_vi"), snapshot.get("name_en")]
    return normalize(" ".join(str(name) for name in names if name))


def tool_domain(name):
    # Registry là nguồn duy nhất về miền của tool, dùng chung với định tuyến và các lượt.
    from agentic.tools.registry import REGISTRY

    spec = REGISTRY.get(name)
    return spec.domain if spec else "other"


class Projector:
    def __init__(self, driver, settings):
        self.driver, self.settings = driver, settings

    async def query(self, query, **params):
        async with self.driver.session(
            database=value(self.settings, "NEO4J_DATABASE", "neo4j")
        ) as session:
            return await (await session.run(query, **params)).data()

    async def initialize(self):
        for label, prop in (
            ("KGEntity", "key"),
            ("KGOwner", "key"),
            ("KGState", "key"),
            ("Intent", "name"),
        ):
            await self.query(
                f"CREATE CONSTRAINT kg_{label.lower()} IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )
        indexes = [
            ("owner_kind", "KGEntity", "(n.owner_id, n.kind)"),
            ("execution_owner", "Execution", "(n.owner_id, n.source_at)"),
            ("day_owner", "Day", "(n.owner_id, n.date)"),
            ("period_owner", "Period", "(n.owner_id, n.grain, n.start)"),
            ("run_owner", "Run", "(n.owner_id, n.at)"),
            # Cypher sinh ra luôn được gắn owner_id; khoảng thời gian đọc theo ngày địa phương.
            *((kind.lower() + "_day", kind, "(n.owner_id, n.local_date)") for kind in DAY_KINDS),
        ]
        for name, label, expression in indexes:
            await self.query(
                f"CREATE INDEX kg_{name} IF NOT EXISTS FOR (n:{label}) ON {expression}"
            )
        await self.query("CREATE INDEX kg_food_scope IF NOT EXISTS FOR (n:Food) ON (n.scope)")
        await self.query(
            "MERGE (s:KGState {key:'main'}) ON CREATE SET s.ready=false, s.generation=1"
        )
        # Đồ thị năng lực (Agent/Tool/Domain/TaskTemplate) chưa từng được đọc: dọn khỏi graph cũ.
        await self.query(
            "MATCH (n) WHERE n:Agent OR n:Tool OR n:Domain OR n:TaskTemplate DETACH DELETE n"
        )
        await self.query("DROP CONSTRAINT kg_agent IF EXISTS")
        await self.query("DROP CONSTRAINT kg_domain IF EXISTS")
        await self.query("DROP CONSTRAINT kg_tool IF EXISTS")
        await self.query("DROP CONSTRAINT kg_tasktemplate IF EXISTS")

    async def apply(self, event: ProjectionEvent):
        if event.schema_version != 1 or event.payload.get("schema_version", 1) != 1:
            raise ValueError("Unsupported projection schema version")
        if event.aggregate_type != "Food" and not event.owner_id:
            raise ValueError("Private projection requires owner_id")
        if event.source != (
            "agent" if event.aggregate_type in {"Execution", "Session", "Run"} else "backend"
        ):
            raise ValueError("Projection source/type mismatch")
        if (
            event.aggregate_type == "Food"
            and event.payload.get("source_type") == "CUSTOM"
            and not event.owner_id
        ):
            raise ValueError("Custom catalog projection requires owner_id")
        async with self.driver.session(
            database=value(self.settings, "NEO4J_DATABASE", "neo4j")
        ) as session:
            return await session.execute_write(self._apply, event)

    async def _apply(self, tx, event):
        # Mọi sự kiện của một chủ sở hữu đều lấy cùng một khoá ghi trước. Nhờ vậy
        # xoá tài khoản an toàn trước tranh chấp, kể cả giữa các database outbox khác nhau.
        if event.owner_id:
            result = await tx.run(
                """
                MERGE (o:KGOwner {key:$owner}) ON CREATE SET o.deleted=false, o.lock=0
                SET o.lock=o.lock+1 RETURN o.deleted AS deleted
            """,
                owner=event.owner_id,
            )
            owner = await result.single()
            if owner["deleted"] and event.aggregate_type != "User":
                return "blocked_owner"
        result = await tx.run(
            """
            MERGE (n:KGEntity {key:$key}) ON CREATE SET n.source_version=0,n.lock=0
            SET n.lock=coalesce(n.lock,0)+1
            RETURN coalesce(n.source_version, 0) AS version, n.session_generation AS generation,
                   n.local_date AS local_date
        """,
            key=event.key,
        )
        previous = await result.single()
        if previous["version"] >= event.aggregate_version:
            return "stale"
        # Ngày cũ của bản ghi: đổi ngày hay xoá đều phải tính lại tổng hợp của ngày đó.
        old_day = to_date(previous["local_date"]) if previous["local_date"] else None
        props, data = event_properties(event)
        label = event.aggregate_type  # Literal đã kiểm tra, không bao giờ là dữ liệu từ request
        if label == "Session" and previous["generation"] is not None:
            props["session_generation"] = previous["generation"]
        if event.aggregate_type in {"Execution", "Run"}:
            statuses = TURN_STATUSES if event.aggregate_type == "Run" else {"succeeded", "failed"}
            if data.get("status") not in statuses:
                raise ValueError("Only actual completed executions and turns can be projected")
            if (
                not data.get("session_id")
                or not data.get("run_id")
                or not isinstance(data.get("session_generation"), int)
            ):
                raise ValueError("Execution requires session/run/generation")
            session_key = "agent:Session:" + data["session_id"]
            record = await (
                await tx.run(
                    """
                MERGE (s:KGEntity:Session {key:$key})
                ON CREATE SET s.source_version=0,s.deleted_through_generation=0,s.owner_id=$owner,s.kind='Session'
                SET s.lock=coalesce(s.lock,0)+1
                RETURN s.deleted_through_generation AS deleted_through, s.owner_id AS owner
            """,
                    key=session_key,
                    owner=event.owner_id,
                )
            ).single()
            if (
                record["owner"] != event.owner_id
                or (record["deleted_through"] or 0) >= data["session_generation"]
            ):
                await tx.run(
                    "MATCH (n:KGEntity {key:$key}) SET n = $props",
                    key=event.key,
                    props=self.tombstone(props),
                )
                return "blocked_session"
        else:
            session_key = None
        if event.operation == "delete":
            await tx.run(
                f"MATCH (n:KGEntity {{key:$key}}) SET n:{label}, n = $props",
                key=event.key,
                props=self.tombstone(props),
            )
            await self._delete(tx, event)
            if label in DAY_KINDS:
                await self._roll_up(tx, event, {old_day})
            return "deleted"
        # Tài khoản đã vô hiệu hoá là trạng thái cuối của phép chiếu này. Bật lại
        # cần dựng lại từ nguồn; sự kiện cũ không thể khôi phục dữ liệu của nó.
        if event.aggregate_type == "User" and owner["deleted"]:
            return "blocked_owner"
        await tx.run(
            f"MATCH (n:KGEntity {{key:$key}}) SET n:{label}, n = $props", key=event.key, props=props
        )
        if event.owner_id:
            await tx.run(
                """
                MERGE (u:KGEntity:User {key:$user_key})
                ON CREATE SET u.owner_id=$owner,u.source_version=0,u.kind='User',u.deleted=false
            """,
                user_key="backend:User:" + event.owner_id,
                owner=event.owner_id,
            )
        if label in RELATIONS:
            await tx.run(
                f"MATCH (u:User {{key:$user_key}}),(n:{label} {{key:$key}}) MERGE (u)-[:{RELATIONS[label]}]->(n)",
                user_key="backend:User:" + event.owner_id,
                key=event.key,
            )
        if label == "Meal":
            await self._meal(tx, event, data)
        if label == "Training":
            await self._training(tx, event, data)
        if label == "Execution":
            await self._execution(tx, event, data, session_key)
        if label == "Run":
            await self._run(tx, event, data, session_key)
        if label in RECORD_KINDS:
            await tx.run(
                """
                MATCH (n:KGEntity {key:$key}), (e:Execution)
                WHERE $key IN e.target_keys AND (e.owner_id=n.owner_id OR (n:Food AND n.scope='SYSTEM'))
                MERGE (e)-[:TARGETS]->(n)
            """,
                key=event.key,
            )
        if label in RECORD_KINDS - {"Food"}:
            # Một lượt có thể được ghi nhật ký trước khi bản ghi nó tạo ra được chiếu.
            await tx.run(
                """
                MATCH (n:KGEntity {key:$key}), (r:KGEntity {owner_id:$owner, kind:'Run'})
                WHERE $key IN coalesce(r.about_keys, [])
                MERGE (r)-[:ABOUT]->(n)
            """,
                key=event.key,
                owner=event.owner_id,
            )
        if label == "Food":
            await tx.run(
                """
                MATCH (f:Food {key:$key}), (i:MealItem {food_key:$key})
                WHERE i.owner_id=f.owner_id OR f.scope='SYSTEM'
                MERGE (i)-[:REFERS_TO]->(f)
            """,
                key=event.key,
            )
        if label in DAY_KINDS:
            await self._roll_up(tx, event, {old_day, props.get("local_date")})
        return "applied"

    async def _roll_up(self, tx, event, days):
        """Tính lại Day và hai Period (tuần, tháng) chứa nó, trong cùng transaction với sự kiện."""
        await tx.run("MATCH (n:KGEntity {key:$key})-[r:ON_DAY]->() DELETE r", key=event.key)
        owner = event.owner_id
        for day in sorted(d for d in days if d):
            day_key = f"day:{owner}:{day.isoformat()}"
            await tx.run(DAY_ROLLUP, key=day_key, owner=owner, date=day, kinds=list(DAY_KINDS))
            for grain, (label, start, end) in (("week", _week(day)), ("month", _month(day))):
                await tx.run(
                    PERIOD_ROLLUP,
                    day_key=day_key,
                    key=f"period:{owner}:{grain}:{label}",
                    owner=owner,
                    grain=grain,
                    label=label,
                    start=start,
                    end=end,
                )

    @staticmethod
    def tombstone(props):
        return {
            key: val
            for key, val in {**props, "deleted": True}.items()
            if key
            in {
                "key",
                "kind",
                "source",
                "source_id",
                "source_version",
                "owner_id",
                "scope",
                "deleted",
                "source_at",
                "projection_version",
                "session_generation",
            }
        }

    async def _delete(self, tx, event):
        if event.aggregate_type == "User":
            await tx.run("MATCH (o:KGOwner {key:$owner}) SET o.deleted=true", owner=event.owner_id)
            await tx.run(
                "MATCH (n:KGEntity) WHERE n.owner_id=$owner AND n.key<>$key DETACH DELETE n",
                owner=event.owner_id,
                key=event.key,
            )
        elif event.aggregate_type == "Session":
            generation = int(event.payload.get("generation", event.aggregate_version))
            await tx.run(
                """
                MATCH (s:Session {key:$key}) SET s.deleted_through_generation=$generation,
                    s.deleted=coalesce(s.session_generation,0)<=$generation
                WITH s MATCH (n:KGEntity)
                WHERE n.owner_id=$owner AND n.session_id=$session_id
                  AND coalesce(n.session_generation,0)<=$generation AND (n:Run OR n:Execution)
                DETACH DELETE n
            """,
                key=event.key,
                generation=generation,
                owner=event.owner_id,
                session_id=event.aggregate_id,
            )
        elif event.aggregate_type == "Meal":
            await tx.run(
                "MATCH (m:Meal {key:$key})-[:HAS_ITEM]->(i:MealItem) DETACH DELETE i", key=event.key
            )
        elif event.aggregate_type == "Training":
            await tx.run("MATCH (t:Training {key:$key})-[r:PERFORMED]->() DELETE r", key=event.key)

    async def _training(self, tx, event, data):
        """Training -[:PERFORMED]-> các node tham chiếu Exercise chỉ mang định danh catalog."""
        await tx.run("MATCH (t:Training {key:$key})-[r:PERFORMED]->() DELETE r", key=event.key)
        rows = []
        for item in data.get("items", []):
            exercise = item.get("exercise") or {}
            if not exercise.get("id"):
                continue
            system = exercise.get("source_type") == "SYSTEM"
            fact = {
                "kind": "Exercise",
                "source": "backend",
                "data": {
                    k: exercise[k] for k in ("name_vi", "name_en", "kind", "code") if k in exercise
                },
            }
            typed = {
                k: exercise[k]
                for k in ("name_vi", "name_en", "kind")
                if exercise.get(k) is not None
            }
            typed["name_search"] = normalize(
                " ".join(filter(None, [exercise.get("name_vi"), exercise.get("name_en")]))
            )
            performed = {
                "hard_sets": item.get("hard_sets"),
                "volume_kg": item.get("volume_kg"),
                "best_e1rm_kg": item.get("best_e1rm_kg"),
                "distance_km": _ratio(item.get("distance_meters"), 1000),
                "duration_min": _ratio(item.get("duration_seconds"), 60),
            }
            rows.append(
                dict(
                    key="backend:Exercise:" + str(exercise["id"]),
                    scope="SYSTEM" if system else "PRIVATE",
                    owner_id=None if system else event.owner_id,
                    position=item.get("position", 0),
                    fact_json=json.dumps(fact, ensure_ascii=False, separators=(",", ":")),
                    typed=typed,
                    performed={
                        k: coerce(REL_PROPS["PERFORMED"][k], v)
                        for k, v in performed.items()
                        if v is not None
                    },
                )
            )
        await tx.run(
            """
            MATCH (t:Training {key:$key}) UNWIND $rows AS row
            MERGE (x:KGEntity:Exercise {key:row.key})
            ON CREATE SET x.source_version=0
            SET x.kind='Exercise',x.scope=row.scope,x.owner_id=row.owner_id,x.fact_json=row.fact_json,x.deleted=false,x.source='backend'
            SET x += row.typed
            MERGE (t)-[p:PERFORMED]->(x) SET p.position=row.position, p += row.performed
        """,
            key=event.key,
            rows=rows,
        )
        if data.get("replaces_id"):
            await tx.run(
                """
                MATCH (t:Training {key:$key})
                MERGE (old:KGEntity:Training {key:$previous})
                ON CREATE SET old.owner_id=$owner,old.source_version=0,old.deleted=true,old.kind='Training'
                WITH t,old WHERE old.owner_id=$owner MERGE (t)-[:REPLACES]->(old)
            """,
                key=event.key,
                previous="backend:Training:" + data["replaces_id"],
                owner=event.owner_id,
            )

    async def _meal(self, tx, event, data):
        await tx.run(
            "MATCH (m:Meal {key:$key})-[:HAS_ITEM]->(i:MealItem) DETACH DELETE i", key=event.key
        )
        rows = []
        for index, item in enumerate(data.get("items", [])):
            food = item.get("food_snapshot") or {}
            typed = typed_properties(
                "MealItem", {**item, "food_name": food.get("name_vi") or food.get("name_en")}
            )
            rows.append(
                dict(
                    key=event.key + ":item:" + str(item.get("id", index)),
                    owner_id=event.owner_id,
                    food_key="backend:Food:" + str(item.get("food_id", "")),
                    snapshot_json=json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                    position=item.get("position", index),
                    typed=typed,
                )
            )
        await tx.run(
            """
            MATCH (m:Meal {key:$key}) UNWIND $rows AS row
            MERGE (i:KGEntity:MealItem {key:row.key})
            SET i.owner_id=row.owner_id,i.kind='MealItem',i.snapshot_json=row.snapshot_json,i.position=row.position,i.food_key=row.food_key,
                i.deleted=false, i += row.typed
            MERGE (m)-[:HAS_ITEM]->(i)
            WITH i,row OPTIONAL MATCH (f:Food {key:row.food_key})
            WHERE f.owner_id=$owner OR f.scope='SYSTEM'
            FOREACH (_ IN CASE WHEN f IS NULL THEN [] ELSE [1] END | MERGE (i)-[:REFERS_TO]->(f))
        """,
            key=event.key,
            rows=rows,
            owner=event.owner_id,
        )
        if data.get("replaces_id"):
            await tx.run(
                """
                MATCH (m:Meal {key:$key})
                MERGE (old:KGEntity:Meal {key:$previous})
                ON CREATE SET old.owner_id=$owner,old.source_version=0,old.deleted=true,old.kind='Meal'
                WITH m,old WHERE old.owner_id=$owner MERGE (m)-[:REPLACES]->(old)
            """,
                key=event.key,
                previous="backend:Meal:" + data["replaces_id"],
                owner=event.owner_id,
            )

    async def _execution(self, tx, event, data, session_key):
        run_key = "agent:Run:" + data["run_id"]
        await tx.run(
            """
            MATCH (s:Session {key:$session_key}),(u:User {key:$user_key}),(e:Execution {key:$key})
            SET s.deleted=false,s.session_generation=$generation
            MERGE (u)-[:HAS_SESSION]->(s)
            MERGE (r:KGEntity:Run {key:$run_key})
            SET r.kind='Run',r.owner_id=$owner,r.session_id=$session_id,r.session_generation=$generation,r.source_at=$source_at
            MERGE (s)-[:HAS_RUN]->(r) MERGE (r)-[:HAS_EXECUTION]->(e)
        """,
            session_key=session_key,
            user_key="backend:User:" + event.owner_id,
            key=event.key,
            run_key=run_key,
            owner=event.owner_id,
            session_id=data["session_id"],
            generation=data["session_generation"],
            source_at=utc_string(event.occurred_at),
        )
        await tx.run(
            """
            MATCH (e:Execution {key:$key}) SET e.target_keys=[ref IN $refs | ref.key]
            WITH e UNWIND $refs AS ref
            MATCH (n:KGEntity {key:ref.key})
            WHERE n.owner_id=$owner OR (n:Food AND n.scope='SYSTEM')
            MERGE (e)-[:TARGETS]->(n)
        """,
            key=event.key,
            owner=event.owner_id,
            refs=[
                {"key": "backend:" + r["kind"] + ":" + r["source_id"]}
                for r in data.get("resource_refs", [])
            ],
        )

    async def _run(self, tx, event, data, session_key):
        await tx.run(
            """
            MATCH (s:Session {key:$session_key}),(u:User {key:$user_key}),(r:Run {key:$key})
            SET s.deleted=false,s.session_generation=$generation,r.about_keys=$refs
            MERGE (u)-[:HAS_SESSION]->(s)
            MERGE (s)-[:HAS_RUN]->(r)
            WITH r
            OPTIONAL MATCH (r)-[old:HAS_INTENT|ABOUT]->()
            DELETE old
            WITH DISTINCT r
            MERGE (i:Intent {name:$intent}) SET i.label=$label, i.hub=$hub
            MERGE (r)-[:HAS_INTENT]->(i)
            WITH r UNWIND $refs AS ref
            MATCH (n:KGEntity {key:ref})
            WHERE n.owner_id=$owner OR (n:Food AND n.scope='SYSTEM')
            MERGE (r)-[:ABOUT]->(n)
        """,
            session_key=session_key,
            user_key="backend:User:" + event.owner_id,
            key=event.key,
            owner=event.owner_id,
            generation=data["session_generation"],
            intent=data["intent"],
            label=intent_label(data["intent"]),
            hub=intent_hub(data["intent"]),
            refs=[
                "backend:" + r["kind"] + ":" + r["source_id"] for r in data.get("resource_refs", [])
            ],
        )
        # Chuỗi quyết định của phiên: lượt trước -[:NEXT]-> lượt này, dù lượt nào được chiếu trước.
        await tx.run(
            """
            MATCH (r:Run {key:$key})
            OPTIONAL MATCH (p:Run {key:r.prev_key}) WHERE p.owner_id=$owner
            FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:NEXT]->(r))
            WITH r
            OPTIONAL MATCH (n:Run {owner_id:$owner, prev_key:$key})
            FOREACH (_ IN CASE WHEN n IS NULL THEN [] ELSE [1] END | MERGE (r)-[:NEXT]->(n))
        """,
            key=event.key,
            owner=event.owner_id,
        )

    async def refresh_model(self, owner, now=None):
        """Tính lại tri thức suy ra của một chủ sở hữu; idempotent và chạy lại an toàn."""
        now = now or datetime.now(timezone.utc)
        cutoff = (
            now - timedelta(days=value(self.settings, "KG_BUSINESS_RETENTION_DAYS", 90))
        ).isoformat()
        rows = await self.query(
            """
            MATCH (o:KGOwner {key:$owner}) WHERE coalesce(o.deleted, false) = false
            MATCH (u:KGEntity {key:$user_key}) WHERE coalesce(u.deleted, false) = false
            OPTIONAL MATCH (n:KGEntity {owner_id:$owner})
            WHERE n.kind IN $kinds AND coalesce(n.deleted, false) = false
              AND n.fact_json IS NOT NULL AND (n.kind IN ['User','Goal'] OR coalesce(n.business_at, n.source_at) >= $cutoff)
            RETURN u.key AS user, collect(n.fact_json) AS facts
        """,
            owner=owner,
            user_key="backend:User:" + owner,
            cutoff=cutoff,
            kinds=sorted(MODEL_SOURCES),
        )
        if (
            not rows
        ):  # chủ sở hữu đã xoá hoặc không rõ; gom nhóm theo người dùng giữ danh sách này rỗng
            return False
        # Chủ sở hữu có lịch sử đã quá hạn vẫn nhận một model (rỗng), để không bị chọn lại ở mỗi chu kỳ.
        model = build_user_model([json.loads(fact) for fact in rows[0]["facts"]], now)
        foods, exercises = model_links(model)
        await self.query(
            """
            MATCH (u:KGEntity {key:$user_key}) WHERE coalesce(u.deleted, false) = false
            MERGE (m:KGEntity {key:$key})
            SET m:UserModel, m.kind='UserModel', m.owner_id=$owner, m.deleted=false, m.model_json=$model,
                m.model_version=$version, m.computed_at=$now, m.today=$today, m.source_at=$now
            MERGE (u)-[:HAS_MODEL]->(m)
            WITH u
            OPTIONAL MATCH (u)-[old:FREQUENTLY_EATS|PRACTICES]->()
            DELETE old
            WITH DISTINCT u
            CALL (u) {
              UNWIND $foods AS food
              MATCH (f:KGEntity {key:food.key}) WHERE f.owner_id=$owner OR f.scope='SYSTEM'
              MERGE (u)-[r:FREQUENTLY_EATS]->(f) SET r.count=food.count, r.last_date=food.last_date
            }
            CALL (u) {
              UNWIND $exercises AS exercise
              MATCH (x:KGEntity {key:exercise.key}) WHERE x.owner_id=$owner OR x.scope='SYSTEM'
              MERGE (u)-[r:PRACTICES]->(x) SET r.sessions=exercise.sessions, r.last_date=exercise.last_date,
                r.best_e1rm_kg=exercise.best_e1rm_kg, r.distance_km=exercise.distance_km
            }
        """,
            user_key="backend:User:" + owner,
            key="model:" + owner,
            owner=owner,
            version=MODEL_VERSION,
            model=json.dumps(model, ensure_ascii=False, separators=(",", ":")),
            now=now.isoformat(),
            today=model["today"],
            foods=foods,
            exercises=exercises,
        )
        return True

    async def stale_model_owners(self, limit=25, now=None):
        """Các chủ sở hữu có model bị thiếu, đã cũ, hoặc được tính vào một ngày địa phương trước đó."""
        now = now or datetime.now(timezone.utc)
        rows = await self.query(
            """
            MATCH (u:KGEntity:User) WHERE coalesce(u.deleted, false) = false AND u.owner_id IS NOT NULL
            OPTIONAL MATCH (u)-[:HAS_MODEL]->(m:UserModel)
            WITH u, m WHERE m IS NULL OR m.today < $today OR m.computed_at < $cutoff OR coalesce(m.model_version, 0) < $version
            RETURN u.owner_id AS owner ORDER BY coalesce(m.computed_at, '') LIMIT $limit
        """,
            today=now.astimezone(LOCAL).date().isoformat(),
            cutoff=(now - timedelta(hours=6)).isoformat(),
            version=MODEL_VERSION,
            limit=limit,
        )
        return [row["owner"] for row in rows]

    async def prune(self):
        """Bản ghi thô quá hạn lưu bị ẩn (deleted) nhưng giữ thuộc tính có kiểu với cờ pruned, để tổng hợp Day/Period
        tính lại vẫn đúng. Mục tiêu đã kết thúc được giữ với trạng thái của nó (lịch sử mục tiêu)."""
        now = datetime.now(timezone.utc)
        for kinds, days, pruned in (
            (
                ["Meal", "BodyMetric", "Training", *HEALTH_KINDS],
                value(self.settings, "KG_BUSINESS_RETENTION_DAYS", 90),
                True,
            ),
            (["Execution", "Run"], value(self.settings, "KG_MEMORY_RETENTION_DAYS", 30), False),
        ):
            await self.query(
                """
              MATCH (n:KGEntity) WHERE n.kind IN $kinds AND coalesce(n.business_at,n.source_at)<$cutoff
                AND coalesce(n.pruned, false) = false AND (n.deleted = false OR n.fact_json IS NOT NULL)
              OPTIONAL MATCH (n)-[:HAS_ITEM]->(item:MealItem)
              DETACH DELETE item
              SET n.fact_json=null,n.search_text=null,n.deleted=true,n.pruned=$pruned
            """,
                kinds=kinds,
                cutoff=(now - timedelta(days=days)).isoformat(),
                pruned=pruned,
            )
