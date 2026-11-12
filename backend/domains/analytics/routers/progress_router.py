"""Tổng thực tế theo ngày và so sánh với chỉ tiêu tường minh của kế hoạch."""
from uuid import UUID

from fastapi import APIRouter

from api.dependencies import DateRangeQueryDep, ProgressRangeQueryDep, UserContextDep
from domains.analytics.schemas.progress import PlanProgressRead, ProgressRead
from domains.analytics.services.progress_service import summarize_plan, summarize_user

router = APIRouter(tags=["progress"])


@router.get("/progress", response_model=ProgressRead)
async def get_progress(options: DateRangeQueryDep, service: UserContextDep):
    return await summarize_user(service.session, user_id=service.user_id, options=options)


@router.get("/plans/{plan_id}/progress", response_model=PlanProgressRead)
async def get_plan_progress(plan_id: UUID, options: ProgressRangeQueryDep, service: UserContextDep):
    return await summarize_plan(service.session, user_id=service.user_id, plan_id=plan_id, **options.model_dump())
