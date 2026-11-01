"""GET /api/v2/operations/{id}: progress and outcome of an asynchronous command."""
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel

from api.dependencies import UserContextDep
from domains.shared import operations

router = APIRouter(prefix="/operations", tags=["operations"])


class OperationJobs(BaseModel):
    total: int
    by_state: dict[str, int]


class OperationRead(BaseModel):
    id: UUID
    kind: str
    state: str
    created_at: datetime
    jobs: OperationJobs
    steps: list[dict[str, Any]]
    exports: dict[str, int]


@router.get("/{operation_id}", response_model=OperationRead, summary="Trạng thái một thao tác bất đồng bộ")
async def get_operation(operation_id: UUID, service: UserContextDep):
    return await operations.read(service.session, service.user_id, operation_id)
