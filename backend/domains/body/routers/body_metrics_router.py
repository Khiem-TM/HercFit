"""Số đo cơ thể bất biến và các lần sửa thuộc về người dùng hiện tại."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from api.dependencies import BodyMetricQueryDep, UserDataServiceDep
from core.idempotency import IdempotentRoute
from core.transaction import transaction
from domains.body.schemas.body_metrics import BodyMetricCreate, BodyMetricRead, BodyMetricReplace

router = APIRouter(route_class=IdempotentRoute, prefix="/body-metrics", tags=["body-metrics"])


@router.post("", response_model=BodyMetricRead, status_code=status.HTTP_201_CREATED)
@transaction
async def create_body_metric(payload: BodyMetricCreate, service: UserDataServiceDep):
    return await service.create_metric(payload)


@router.get("", response_model=list[BodyMetricRead])
async def list_body_metrics(options: BodyMetricQueryDep, service: UserDataServiceDep):
    return await service.list_metrics(options)


@router.get("/latest", response_model=BodyMetricRead)
async def get_latest_body_metric(service: UserDataServiceDep):
    return await service.latest_metric()


@router.get("/{metric_id}", response_model=BodyMetricRead)
async def get_body_metric(metric_id: UUID, service: UserDataServiceDep):
    return await service.get_metric(metric_id)


@router.put("/{metric_id}", response_model=BodyMetricRead)
@transaction
async def replace_body_metric(metric_id: UUID, payload: BodyMetricReplace, service: UserDataServiceDep):
    """Trả về ID snapshot mới, giữ recorded_at khi không truyền."""
    return await service.replace_metric(metric_id, payload)


@router.delete("/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
@transaction
async def delete_body_metric(metric_id: UUID, service: UserDataServiceDep) -> Response:
    await service.delete_metric(metric_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
