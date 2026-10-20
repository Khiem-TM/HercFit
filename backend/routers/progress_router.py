"""Daily actual totals and comparisons to explicit plan targets."""
from uuid import UUID

from fastapi import APIRouter
from routers.dependencies import UserContextDep, DateRangeQueryDep, ProgressRangeQueryDep
from schemas.progress import ProgressRead, PlanProgressRead
from services.progress_service import summarize_user, summarize_plan

router = APIRouter(tags=["progress"])


@router.get("/progress", response_model=ProgressRead)
async def get_progress(options: DateRangeQueryDep, service: UserContextDep):
    return await summarize_user(service.session, user_id=service.user_id, options=options)


@router.get("/plans/{plan_id}/progress", response_model=PlanProgressRead)
async def get_plan_progress(plan_id: UUID, options: ProgressRangeQueryDep, service: UserContextDep):
    return await summarize_plan(service.session, user_id=service.user_id, plan_id=plan_id, **options.model_dump())
