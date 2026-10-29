"""Authenticated cover-image operations for all four activity/catalog types."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile
from routers.dependencies import service_dependency, VersionQuery
from schemas.media import ImageEntity, ImageImport, ImageRead
from services.media_service import MediaService

router = APIRouter(prefix="/media", tags=["images"])
MediaServiceDep = Annotated[MediaService, service_dependency(MediaService)]


@router.get("/{kind}/{entity_id}/image", response_model=ImageRead)
async def get_image(kind: ImageEntity, entity_id: UUID, service: MediaServiceDep):
    return await service.get(kind, entity_id)


@router.put("/{kind}/{entity_id}/image", response_model=ImageRead)
async def upload_image(kind: ImageEntity, entity_id: UUID, service: MediaServiceDep,
                       expected_version_id: Annotated[int, Form(ge=1)],
                       file: Annotated[UploadFile, File()]):
    return await service.upload(kind, entity_id, expected_version_id, file)


@router.post("/{kind}/{entity_id}/image/import", response_model=ImageRead)
async def import_image(kind: ImageEntity, entity_id: UUID, payload: ImageImport, service: MediaServiceDep):
    """Store a research illustration the user kept on a confirmation card."""
    return await service.import_remote(kind, entity_id, payload.expected_version_id, payload.source_url)


@router.delete("/{kind}/{entity_id}/image", response_model=ImageRead)
async def delete_image(kind: ImageEntity, entity_id: UUID, expected_version_id: VersionQuery,
                       service: MediaServiceDep):
    return await service.remove(kind, entity_id, expected_version_id)
