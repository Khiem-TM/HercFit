"""Đẩy buổi gym, bữa ăn và bản ghi sức khoẻ người dùng nhập của HercFit lên Google Health (HercFit là nguồn sự thật).

* Buổi gym → MỘT exercise STRENGTH_TRAINING: khoảng thời gian, thời lượng, kcal và tóm tắt số hiệp.
* Bữa ăn → mỗi món một nutrition-log "thực phẩm ẩn danh" theo docs dinh dưỡng.

Việc cần làm được tìm bằng SQL trên trainings/meals và google_pushes, không có outbox:
* bản ghi active trong cửa sổ chưa có dòng google_pushes, hoặc dòng có pushed_at NULL → tạo
  (xoá trước các điểm cũ của dòng đó nếu HercFit sở hữu);
* bản ghi đã bị thay hoặc xoá (is_active = false) còn dòng google_pushes → batchDelete rồi bỏ dòng.
Sửa = xoá bản cũ + tạo bản mới. Nutrition-log ẩn danh không sửa được nên đây là cách duy nhất,
và exercise đi cùng một đường cho gọn.

Không bao giờ POST hai lần cho cùng một bản ghi: Google tự cấp id và không có operations.get. Trước
khi tạo, HercFit tìm điểm do chính nó ghi (reconcile self-sources) có cùng thời điểm bắt đầu (và
cùng tên món) mà chưa thuộc dòng nào thì nhận lại điểm đó; một lần tạo bị sập giữa chừng vì thế
được nhận lại ở lượt sau. Buổi gym trùng ≥ 50% với phiên mà đồng hồ đã ghi thì chỉ gắn vào phiên
đó (owned = false), kể cả khi đồng hồ đồng bộ muộn hơn lúc đẩy.

Bản ghi sức khoẻ người dùng nhập (buổi thể thao, nước, giấc ngủ, số đo) nằm sẵn trong health_points với
remote_name "local/..." (records.py). Mỗi dòng như vậy được tạo trên Google (hoặc nhận lại một điểm
HercFit đã tạo mà chưa kịp gắn: pull không đọc điểm đó về, xem pull.orphans) rồi đổi remote_name thành tên
Google; lần pull sau cập nhật đúng dòng đó.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text, update

from core.database import get_db_session
from domains.health_records.models.health_points import HealthPoint
from domains.health_records.types import can_write, spec
from domains.nutrition.models.meals import Meal
from domains.training.models.trainings import Training
from integrations.google_health import fencing, kinds
from integrations.google_health.client import (
    PERMISSION,
    SCHEMA,
    UNSUPPORTED,
    GoogleHealthClient,
    GoogleHealthError,
)
from integrations.google_health.models import GooglePush
from integrations.google_health.pull import adoption_key as _key
from integrations.google_health.pull import fetch
from integrations.google_health.records import LOCAL_PREFIX, LOCAL_TYPES

logger = logging.getLogger(__name__)
GYM_EXERCISE_TYPE = "STRENGTH_TRAINING"
SAME_SESSION_OVERLAP = 0.5
DATA_TYPE = {"Training": "exercise", "Meal": "nutrition-log"}


def overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> float:
    """Phần chồng lấn so với buổi ngắn hơn (0..1)."""
    shared = (min(a_end, b_end) - max(a_start, b_start)).total_seconds()
    shorter = min((a_end - a_start).total_seconds(), (b_end - b_start).total_seconds())
    return shared / shorter if shorter > 0 and shared > 0 else 0.0


def training_span(training: Training) -> tuple[datetime, datetime] | None:
    seconds = float(training.duration_seconds) if training.duration_seconds else sum(
        float(item.duration_seconds or 0) for item in training.items)
    end = training.ended_at or (training.started_at + timedelta(seconds=seconds) if seconds else None)
    return (training.started_at, end) if end is not None and end > training.started_at else None


# ------------------------------------------------------------------------------ ánh xạ
def training_point(training: Training) -> dict[str, Any] | None:
    span = training_span(training)
    if span is None:
        return None  # không có khoảng thời gian trung thực thì không có gì để ghi
    sets = sum(item.working_sets or 0 for item in training.items)
    volume = sum(float(item.volume_kg or 0) for item in training.items)
    exercises = ", ".join(name for name in dict.fromkeys(
        (item.exercise_snapshot or {}).get("name_vi") for item in training.items) if name)
    notes = "; ".join(part for part in (exercises, f"{sets} hiệp" if sets else "",
                                         f"{volume:.0f} kg volume" if volume else "") if part)
    return kinds.Session.build_exercise(
        start=span[0], end=span[1], zone=training.timezone, exercise_type=GYM_EXERCISE_TYPE, name=training.name,
        active_seconds=(span[1] - span[0]).total_seconds(),
        kcal=float(training.energy_kcal) if training.energy_kcal is not None else None, notes=notes or None)


def meal_points(meal: Meal) -> list[dict[str, Any]]:
    def grams(value: Any) -> float | None:
        return float(value) if value is not None else None

    points = []
    for item in meal.items:
        snapshot = item.food_snapshot or {}
        # Mỗi món lệch một giây để mỗi nutrition-log có thời điểm bắt đầu riêng (dùng khi nhận lại).
        points.append(kinds.Food.build_nutrition_log(
            name=snapshot.get("name_vi") or snapshot.get("name_en") or meal.name,
            start=meal.consumed_at + timedelta(seconds=item.position), zone=meal.timezone,
            kcal=grams(item.energy_kcal), carbohydrate_g=grams(item.carbohydrate_g), fat_g=grams(item.fat_g),
            protein_g=grams(item.protein_g), fiber_g=grams(item.fiber_g), amount=grams(item.quantity), unit=item.unit))
    return points


# ------------------------------------------------------------------------------ Google
class Pusher:
    def __init__(self, client: GoogleHealthClient, user_id: UUID, start: date, end: date, zone: str):
        self.client, self.user_id, self.start, self.end, self.zone = client, user_id, start, end, zone
        self.counts = {"created": 0, "adopted": 0, "linked": 0, "deleted": 0, "failed": 0}
        self.own: dict[str, dict[tuple[str, ...], str]] = {}
        self.own_values: dict[str, dict] = {}

    async def load_own(self, known: set[str], data_types: tuple[str, ...] = tuple(DATA_TYPE.values())) -> None:
        """Điểm do HercFit ghi trong cửa sổ mà chưa thuộc dòng google_pushes nào (để nhận lại)."""
        for data_type in dict.fromkeys(data_types):
            points, _complete = await fetch(self.client, spec(data_type), self.start, self.end, self.zone,
                                            family="self-sources")
            self.own[data_type] = {_key(data_type, {spec(data_type).field: point.value}): point.remote_name
                                   for point in points if point.remote_name not in known}
            self.own_values.update({point.remote_name: point.value for point in points})

    async def delete(self, data_type: str, names: list[str]) -> None:
        if not names:
            return
        try:
            await fencing.before_request()
            await self.client.batch_delete(data_type, names)
        except GoogleHealthError as exc:
            if exc.status != 404:  # đã không còn trên Google: coi như đã xoá
                raise
        self.counts["deleted"] += len(names)

    async def create(self, data_type: str, payload: dict[str, Any]) -> str | None:
        """Tên điểm trên Google; None khi Operation chưa xong (lượt sau sẽ nhận lại qua self-sources)."""
        if (name := self.own.get(data_type, {}).pop(_key(data_type, payload), None)) is not None:
            # A time match alone must never adopt an older value of a locally edited point.
            if data_type not in LOCAL_TYPES or self.own_values.get(name) == payload.get(spec(data_type).field):
                self.counts["adopted"] += 1
                return name
        await fencing.before_request()
        operation = await self.client.create_point(data_type, payload)
        if operation.get("error"):
            raise GoogleHealthError(f"operation:{(operation['error'] or {}).get('code')}", None, SCHEMA)
        self.counts["created"] += 1
        return (operation.get("response") or {}).get("name") if operation.get("done") else None


async def _save(record_type: str, record_id: UUID, user_id: UUID, **values: Any) -> None:
    async with get_db_session() as session:
        await fencing.check(session)
        row = await session.get(GooglePush, (record_type, record_id))
        if row is None:
            session.add(GooglePush(record_type=record_type, record_id=record_id, user_id=user_id, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)


async def _forget(record_type: str, record_id: UUID) -> None:
    async with get_db_session() as session:
        await fencing.check(session)
        await session.execute(text("DELETE FROM google_pushes WHERE record_type = :t AND record_id = :r"),
                              {"t": record_type, "r": record_id})


async def _device_sessions(user_id: UUID, start: date, end: date) -> list[HealthPoint]:
    async with get_db_session() as session:
        return list((await session.execute(select(HealthPoint).where(
            HealthPoint.user_id == user_id, HealthPoint.data_type == "exercise",
            HealthPoint.written_by_hercfit.is_(False), HealthPoint.local_date >= start - timedelta(days=1),
            HealthPoint.local_date < end))).scalars())


def _device_match(span: tuple[datetime, datetime], sessions: list[HealthPoint]) -> str | None:
    best = max(sessions, default=None, key=lambda point: overlap(*span, point.start_at, point.end_at))
    if best is not None and overlap(*span, best.start_at, best.end_at) >= SAME_SESSION_OVERLAP:
        return best.remote_name
    return None


# ------------------------------------------------------------------------------ một lượt đẩy
async def push_pending(client: GoogleHealthClient, user_id: UUID, start: date, end: date, zone: str,
                       granted: list[str] | tuple[str, ...] = ()) -> dict[str, int]:
    """`granted`: scope của kết nối; bản ghi cục bộ chỉ được đẩy với loại có quyền ghi."""
    local_types = tuple(data_type for data_type in LOCAL_TYPES if can_write(data_type, granted))
    async with get_db_session() as session:
        pushes = {(row.record_type, row.record_id): row for row in (await session.execute(
            select(GooglePush).where(GooglePush.user_id == user_id))).scalars()}
        lower, upper = (datetime.combine(day, time.min, ZoneInfo(zone)) for day in (start, end))
        records: dict[str, list[Any]] = {}
        for record_type, model, column in (("Training", Training, Training.started_at),
                                           ("Meal", Meal, Meal.consumed_at)):
            records[record_type] = list((await session.execute(
                model._user_query(user_id).where(column >= lower, column < upper))).scalars())
        alive = {(kind, record_id) for kind, record_id in (await session.execute(text("""
            SELECT 'Training', id FROM trainings WHERE user_id = :u AND is_active
            UNION ALL SELECT 'Meal', id FROM meals WHERE user_id = :u AND is_active"""), {"u": user_id})).all()}
        # Điểm đã thuộc một dòng health_points (kể cả bản ghi người dùng đã đẩy) không bao giờ được nhận lại lần nữa.
        stored = set((await session.execute(select(HealthPoint.remote_name).where(
            HealthPoint.user_id == user_id, HealthPoint.data_type.in_(local_types),
            HealthPoint.remote_name.not_like(LOCAL_PREFIX + "%")))).scalars()) if local_types else set()
    pusher = Pusher(client, user_id, start, end, zone)
    try:
        await _cleanup_local(pusher)
        # 1. Bản ghi đã bị thay hoặc xoá: gỡ điểm HercFit tạo.
        for key, row in pushes.items():
            if key not in alive:
                if row.owned:
                    await pusher.delete(DATA_TYPE[row.record_type], list(row.names))
                await _forget(*key)
        # 2. Tạo / tạo lại / gắn vào phiên đồng hồ.
        await pusher.load_own({name for row in pushes.values() for name in row.names} | stored,
                              (*DATA_TYPE.values(), *local_types))
        devices = await _device_sessions(user_id, start, end)
        for record_type, rows in records.items():
            for record in rows:
                row = pushes.get((record_type, record.id))
                linked_late = (record_type == "Training" and row is not None and row.owned and row.pushed_at
                               and (span := training_span(record)) and _device_match(span, devices))
                if row is not None and row.pushed_at is not None and not linked_late:
                    continue
                await _push_one(pusher, record_type, record, row, devices)
        # 3. Bản ghi sức khoẻ người dùng nhập còn ở dạng cục bộ.
        await _push_local(pusher, local_types)
    except GoogleHealthError as exc:
        if exc.error_class != PERMISSION:
            raise
        logger.warning("google_health_push_blocked user=%s code=%s", user_id, exc.code)
    finally:
        # Điểm vừa được nhận lại (hay tạo) cho gym / bữa ăn có thể đã được pull đọc vào như dữ liệu Google:
        # bỏ chúng khỏi health_points để mỗi buổi chỉ đếm một lần.
        async with get_db_session() as session:
            await fencing.check(session)
            await session.execute(text("""
                DELETE FROM health_points h USING google_pushes p
                WHERE h.user_id = :u AND p.user_id = :u AND p.owned AND h.remote_name = ANY(p.names)"""), {"u": user_id})
    return pusher.counts


async def _cleanup_local(pusher: Pusher):
    """A stale push is durably excluded from pull until its remote copy is removed."""
    async with get_db_session() as session:
        rows = (await session.execute(text(
            "SELECT data_type, remote_name FROM health_push_cleanup WHERE user_id = :u"),
            {"u": pusher.user_id})).all()
    for data_type, name in rows:
        await pusher.delete(data_type, [name])
        async with get_db_session() as session:
            await fencing.check(session)
            await session.execute(text("DELETE FROM health_push_cleanup WHERE user_id=:u "
                                       "AND data_type=:t AND remote_name=:n"),
                                  {"u": pusher.user_id, "t": data_type, "n": name})


async def _push_local(pusher: Pusher, data_types: tuple[str, ...]) -> None:
    """Tạo trên Google từng dòng "local/..." trong cửa sổ rồi đổi remote_name của chính dòng đó thành tên Google.

    Lỗi của một dòng không chặn các dòng khác (trừ lỗi quyền, dừng cả lượt như gym / bữa ăn)."""
    if not data_types:
        return
    async with get_db_session() as session:
        rows = list((await session.execute(select(HealthPoint).where(
            HealthPoint.user_id == pusher.user_id, HealthPoint.data_type.in_(data_types),
            HealthPoint.remote_name.like(LOCAL_PREFIX + "%"),
            HealthPoint.local_date >= pusher.start, HealthPoint.local_date < pusher.end))).scalars())
    for row in rows:
        payload = {"dataSource": kinds.MANUAL, spec(row.data_type).field: row.value}
        try:
            name = await pusher.create(row.data_type, payload)
        except GoogleHealthError as exc:
            pusher.counts["failed"] += 1
            if exc.error_class == PERMISSION:
                raise
            logger.warning("google_health_local_push_failed type=%s code=%s", row.data_type, exc.code)
            continue
        if name is None:
            continue  # Operation chưa xong: lượt sau nhận lại qua self-sources
        async with get_db_session() as session:
            await fencing.check(session)
            # Chỉ đổi tên khi dòng vẫn là bản cục bộ đã đọc (người dùng có thể vừa sửa hoặc xoá nó).
            changed = await session.execute(update(HealthPoint).where(
                HealthPoint.id == row.id, HealthPoint.remote_name == row.remote_name,
                HealthPoint.revision == row.revision,
            ).values(remote_name=name, updated_at=func.now()))
            if not changed.rowcount:
                await session.execute(text("INSERT INTO health_push_cleanup VALUES (:u,:t,:n) "
                                           "ON CONFLICT DO NOTHING"),
                                      {"u": pusher.user_id, "t": row.data_type, "n": name})
    await _cleanup_local(pusher)


async def _push_one(pusher: Pusher, record_type: str, record: Any, row: GooglePush | None,
                    devices: list[HealthPoint]) -> None:
    data_type = DATA_TYPE[record_type]
    if row is not None and row.owned:
        await pusher.delete(data_type, list(row.names))
    if record_type == "Training" and (span := training_span(record)) and (device := _device_match(span, devices)):
        await _save(record_type, record.id, pusher.user_id, names=[device], owned=False,
                    pushed_at=datetime.now().astimezone(), error=None)
        pusher.counts["linked"] += 1
        return
    payloads = [p for p in [training_point(record)] if p] if record_type == "Training" else meal_points(record)
    if not payloads:
        await _save(record_type, record.id, pusher.user_id, names=[], owned=True,
                    pushed_at=datetime.now().astimezone(), error="nothing_to_write")
        return
    names: list[str] = []
    try:
        for payload in payloads:
            if (name := await pusher.create(data_type, payload)) is not None:
                names.append(name)
    except GoogleHealthError as exc:
        pusher.counts["failed"] += 1
        permanent = exc.error_class in (SCHEMA, UNSUPPORTED)
        # Lỗi vĩnh viễn (request sai) thì dừng; lỗi tạm thời để pushed_at NULL và thử lại lượt sau.
        await _save(record_type, record.id, pusher.user_id, names=names, owned=True, error=exc.code[:120],
                    pushed_at=datetime.now().astimezone() if permanent else None)
        if exc.error_class == PERMISSION:
            raise
        return
    complete = len(names) == len(payloads)
    await _save(record_type, record.id, pusher.user_id, names=names, owned=True, error=None,
                pushed_at=datetime.now().astimezone() if complete else None)
