"""One cover image per entity; optimistic locking and durable cleanup tickets."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from core.settings import settings
from models.domain import require_version
from models.exercises import Exercise
from models.foods import FoodItem
from models.journals import Meal, Training
from models.media import ImageCleanup
from schemas.media import ImageRead
from services.cloudinary_images import CloudinaryImages, read_image
from services.remote_image import fetch_remote_image
from services.common import UserService

MODELS = {"foods": FoodItem, "exercises": Exercise, "meals": Meal, "trainings": Training}


class MediaService(UserService):
    async def entity(self, kind, entity_id, *, write=False, lock=False):
        model = MODELS[kind]
        if kind in {"foods", "exercises"}:
            query = model._visible_query(self.user_id)
            if write:
                query = query.where(model.owner_user_id == self.user_id, model.source_type == "CUSTOM")
        else:
            query = select(model).where(model.user_id == self.user_id, model.is_active.is_(True))
        query = query.where(model.id == entity_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        entity = await self.session.scalar(query)
        if entity is None:
            raise HTTPException(404, "Không tìm thấy bản ghi có quyền truy cập")
        return entity

    @staticmethod
    def response(entity):
        return ImageRead(entity_id=entity.id, image_url=entity.image_url, version_id=entity.version_id)

    async def get(self, kind, entity_id):
        return self.response(await self.entity(kind, entity_id))

    async def queue_old(self, entity, cloud_name):
        if entity.image_public_id:
            # Managed URLs carry their original cloud name; never delete arbitrary URLs.
            parsed = urlparse(entity.image_url or "")
            old_cloud = parsed.path.split("/")[1] if parsed.netloc == "res.cloudinary.com" else cloud_name
            await self.session.execute(insert(ImageCleanup).values(
                public_id=entity.image_public_id, cloud_name=old_cloud,
            ).on_conflict_do_nothing())

    async def upload(self, kind, entity_id, expected_version_id, file):
        entity = await self.entity(kind, entity_id, write=True)
        require_version(entity, expected_version_id)
        cloud = CloudinaryImages()  # fail fast when storage is not configured
        return await self._store(kind, entity_id, expected_version_id, await read_image(file), cloud)

    async def import_remote(self, kind, entity_id, expected_version_id, source_url):
        """Research illustration chosen on a confirmation card, re-hosted on Cloudinary."""
        entity = await self.entity(kind, entity_id, write=True)
        require_version(entity, expected_version_id)
        cloud = CloudinaryImages()
        return await self._store(kind, entity_id, expected_version_id, await fetch_remote_image(source_url), cloud)

    async def _store(self, kind, entity_id, expected_version_id, image, cloud):
        public_id = f"{settings.CLOUDINARY_FOLDER}/{kind}/{entity_id}/{uuid4().hex}"
        # Commit a cleanup ticket BEFORE network I/O. A crash or DB failure later
        # leaves a durable ticket; the worker waits an hour for in-flight requests.
        self.session.add(ImageCleanup(public_id=public_id, cloud_name=cloud.cloud_name,
                                      available_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        await self.session.commit()
        try:
            url = await cloud.upload(image, public_id)
            entity = await self.entity(kind, entity_id, write=True, lock=True)
            require_version(entity, expected_version_id)
            await self.queue_old(entity, cloud.cloud_name)
            entity.image_url = url
            entity.image_public_id = public_id
            await self.session.execute(delete(ImageCleanup).where(ImageCleanup.public_id == public_id))
            await self.session.flush()
            response = self.response(entity)
            await self.session.commit()
            return response
        except Exception:
            await self.session.rollback()
            raise

    async def remove(self, kind, entity_id, expected_version_id):
        entity = await self.entity(kind, entity_id, write=True, lock=True)
        require_version(entity, expected_version_id)
        if entity.image_public_id:
            cloud = CloudinaryImages()
            await self.queue_old(entity, cloud.cloud_name)
        entity.image_url = None
        entity.image_public_id = None
        await self.session.flush()
        response = self.response(entity)
        await self.session.commit()
        return response
