"""Router HTTP của miền ảnh."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile

from api.dependencies import VersionQuery, service_dependency
from domains.media.schemas import ImageEntity, ImageImport, ImageRead
from domains.media.services import MediaService

# --------------------------------------------------------------------------------------------------
# Thao tác ảnh bìa đã xác thực cho cả bốn loại hoạt động/catalog.
# --------------------------------------------------------------------------------------------------

media_router = APIRouter(prefix="/media", tags=["images"])
MediaServiceDep = Annotated[MediaService, service_dependency(MediaService)]


@media_router.get("/{kind}/{entity_id}/image", response_model=ImageRead)
async def get_image(kind: ImageEntity, entity_id: UUID, service: MediaServiceDep):
    return await service.get(kind, entity_id)


@media_router.put("/{kind}/{entity_id}/image", response_model=ImageRead)
async def upload_image(kind: ImageEntity, entity_id: UUID, service: MediaServiceDep,
                       expected_version_id: Annotated[int, Form(ge=1)],
                       file: Annotated[UploadFile, File()]):
    return await service.upload(kind, entity_id, expected_version_id, file)


@media_router.post("/{kind}/{entity_id}/image/import", response_model=ImageRead)
async def import_image(kind: ImageEntity, entity_id: UUID, payload: ImageImport, service: MediaServiceDep):
    """Lưu ảnh minh hoạ từ tra cứu mà người dùng đã giữ trên thẻ xác nhận."""
    return await service.import_remote(kind, entity_id, payload.expected_version_id, payload.source_url)


@media_router.delete("/{kind}/{entity_id}/image", response_model=ImageRead)
async def delete_image(kind: ImageEntity, entity_id: UUID, expected_version_id: VersionQuery,
                       service: MediaServiceDep):
    return await service.remove(kind, entity_id, expected_version_id)
