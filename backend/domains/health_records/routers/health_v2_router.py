"""/api/v2/health: phiên ngủ / buổi tập kèm chi tiết và insight (nền 28 ngày, độ phủ dữ liệu).

Phân trang bằng cursor; trợ lý cần consent thiết bị (identity.consent). Lệnh ghi xuyên qua lên
Google (buổi thể thao, cân nặng, nước...) nằm ở /api/v2/health/records (integrations/google_health).
"""
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import UserContextDep
from domains.analytics.schemas.daily_health import DailyAssessmentRead
from domains.analytics.services import coverage as coverage_service
from domains.analytics.services.daily_health import service as daily_health
from domains.health_records import ports, views
from domains.identity import consent
from domains.shared.schemas.tracking import TimeZoneName

router = APIRouter(prefix="/health", tags=["health-data"])


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None


def _cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if not value:
        return None
    try:
        moment, item = value.split("|", 1)
        return datetime.fromisoformat(moment), UUID(item)
    except ValueError:
        raise HTTPException(422, "Invalid cursor") from None


@router.get("/sessions", response_model=Page, summary="Phiên ngủ / buổi tập trên Google Health kèm chi tiết")
async def sessions(service: UserContextDep, kind: Literal["sleep", "workout"], start_date: date, end_date: date,
                   cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    await consent.require_device_access(service.session, service.user_id)
    rows, field = ((await views.sleep_rows(service.session, service.user_id, start_date, end_date), "start_at")
                   if kind == "sleep" else
                   (await views.workout_rows(service.session, service.user_id, start_date, end_date), "started_at"))
    rows.sort(key=lambda row: (row[field], str(row["id"])), reverse=True)
    after = _cursor(cursor)
    if after:
        rows = [row for row in rows if (row[field], str(row["id"])) < (after[0], str(after[1]))]
    page = rows[:limit]
    return Page(items=page, next_cursor=f"{page[-1][field].isoformat()}|{page[-1]['id']}" if len(rows) > limit else None)


@router.get("/insights", summary="Phân tích có phương pháp: nền 28 ngày và độ phủ dữ liệu")
async def insights(service: UserContextDep, days: Annotated[int, Query(ge=7, le=90)] = 28,
                   end_date: date | None = None, timezone: TimeZoneName | None = None):
    await consent.require_device_access(service.session, service.user_id)
    zone = await ports.user_timezone(service.session, service.user_id, timezone)
    today = datetime.now(ZoneInfo(zone)).date()
    end = end_date or today
    start = end - timedelta(days=days - 1)
    report = await coverage_service.coverage(service.session, service.user_id, start, end)
    baselines = await coverage_service.baselines_for(service.session, service.user_id, end, days, today=today)
    return {
        "start_date": start, "end_date": end, "timezone": zone,
        "baselines": [{"metric": b.metric, "label": coverage_service.BASELINE_METRICS[b.metric], "value": b.value,
                       "spread": b.spread, "mad": b.mad, "n": b.n, "window_days": b.window_days, "as_of": b.as_of,
                       "method": "median of complete days before as_of", "algorithm_version": b.algorithm_version}
                      for b in baselines.values()],
        "coverage": {column: {key: value for key, value in entry.items() if key != "by_day"}
                     for column, entry in report.items()},
    }


@router.get("/daily-assessment", response_model=DailyAssessmentRead, response_model_exclude_none=True,
            summary="Đánh giá sức khoẻ hằng ngày: chỉ số so với nền cá nhân, xu hướng và độ sẵn sàng tập luyện",
            description="Tất định, tính lúc đọc (domains/analytics/services/daily_health). Mỗi lý do mang giá trị, "
                        "đường nền và đơn vị; thiếu dữ liệu được nêu rõ. Heuristic gợi ý cường độ tập, không phải "
                        "chẩn đoán. Trợ lý cần consent thiết bị.")
async def daily_assessment(service: UserContextDep, day: Annotated[date | None, Query(alias="date")] = None,
                           timezone: TimeZoneName | None = None):
    await consent.require_device_access(service.session, service.user_id)
    return await daily_health.assess(service.session, service.user, day=day, zone=timezone)
