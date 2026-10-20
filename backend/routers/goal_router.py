"""Confirm, inspect and manage the authenticated user's goals."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from core.transaction import transaction
from routers.dependencies import PaginationDep, UserDataServiceDep
from schemas.goal import GoalCreate, GoalRead, GoalUpdateRequest

router = APIRouter(prefix="/goals", tags=["goals"])


@router.post("/confirm", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
@transaction
async def confirm_goal(payload: GoalCreate, service: UserDataServiceDep):
    """Persist an accepted goal as IN_PROGRESS; a second current goal returns 409."""
    return await service.confirm_goal(payload)


@router.get("", response_model=list[GoalRead])
async def list_goals(options: PaginationDep, service: UserDataServiceDep):
    return await service.list_goals(options)


@router.get("/current", response_model=GoalRead)
async def get_current_goal(service: UserDataServiceDep):
    return await service.current_goal()


@router.get("/{goal_id}", response_model=GoalRead)
async def get_goal(goal_id: UUID, service: UserDataServiceDep):
    return await service.get_goal(goal_id)


@router.patch("/{goal_id}", response_model=GoalRead)
@transaction
async def update_goal(goal_id: UUID, payload: GoalUpdateRequest, service: UserDataServiceDep):
    return await service.update_goal(goal_id, payload)


@router.post("/{goal_id}/complete", response_model=GoalRead)
@transaction
async def complete_goal(goal_id: UUID, service: UserDataServiceDep):
    return await service.complete_goal(goal_id)


@router.post("/{goal_id}/cancel", response_model=GoalRead)
@transaction
async def cancel_goal(goal_id: UUID, service: UserDataServiceDep):
    return await service.cancel_goal(goal_id)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
@transaction
async def delete_goal(goal_id: UUID, service: UserDataServiceDep) -> Response:
    await service.delete_goal(goal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
