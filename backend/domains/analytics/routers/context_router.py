"""/api/v2/assistant/context: ngữ cảnh có nguồn, có ngân sách cho trợ lý (và cho chính người dùng xem)."""
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.dependencies import UserContextDep
from domains.analytics.services import context_api
from domains.shared.schemas.tracking import TimeZoneName

router = APIRouter(prefix="/assistant", tags=["assistant"])
Topic = Literal["overview", "activity", "sleep", "recovery", "body", "nutrition", "vitals"]
Period = Literal["7d", "28d", "90d"]


class ContextRead(BaseModel):
    topic: str
    period: str
    items: list[dict]
    withheld: list[str]
    consent_version: int
    truncated: int
    tokens: int
    budget: int


class ContextQueryRead(BaseModel):
    sections: list[ContextRead]
    tokens: int
    budget: int


@router.get("/context", response_model=ContextRead, summary="Ngữ cảnh sức khoẻ có nguồn gốc cho trợ lý",
            description="Mỗi mục có giá trị, đơn vị, nguồn, thời điểm đo, độ mới, độ phủ dữ liệu và phương pháp. "
                        "Dữ liệu thiết bị cần đồng ý của người dùng; dữ liệu nhạy cảm cần đồng ý riêng.")
async def get_context(service: UserContextDep, topic: Topic = "overview", period: Period = "28d",
                      budget: Annotated[int, Query(ge=200, le=context_api.BASE_BUDGET * 2)] = context_api.BASE_BUDGET,
                      timezone: TimeZoneName = "Asia/Ho_Chi_Minh"):
    context = await context_api.get(service.session, service.user, topic=topic, period=period, budget=budget,
                                    zone=timezone)
    await service.session.commit()
    return context


@router.get("/context:query", response_model=ContextQueryRead, summary="Truy vấn ngữ cảnh sâu theo chủ đề",
            description="Chỉ đọc (GET): nhiều chủ đề trong một ngân sách token, mặc định 4.000.")
async def query_context(service: UserContextDep, topics: Annotated[list[Topic], Query(min_length=1, max_length=8)],
                        period: Period = "28d",
                        budget: Annotated[int, Query(ge=200, le=8000)] = context_api.DEEP_BUDGET,
                        timezone: TimeZoneName = "Asia/Ho_Chi_Minh"):
    sections, used = [], 0
    for topic in dict.fromkeys(topics):
        remaining = budget - used
        if remaining < 100:
            break
        section = await context_api.get(service.session, service.user, topic=topic, period=period,
                                        budget=remaining, zone=timezone)
        sections.append(section)
        used += section["tokens"]
    await service.session.commit()
    return ContextQueryRead(sections=sections, tokens=used, budget=budget)
