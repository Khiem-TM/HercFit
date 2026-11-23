"""Service nghiệp vụ của miền ảnh."""

import asyncio
import ipaddress
import logging
import socket
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx
from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from starlette.concurrency import run_in_threadpool

from agentic.observability import observed
from core.database import close_crud_db_pool, get_db_session
from core.settings import settings
from domains.catalog.models import Exercise, FoodItem
from domains.media.models import ImageCleanup
from domains.media.schemas import ImageRead
from domains.nutrition.models import Meal
from domains.shared.models import require_version
from domains.shared.services import UserService
from domains.training.models import Training

# --------------------------------------------------------------------------------------------------
# Giải mã ảnh có giới hạn và request Cloudinary đã xác thực, chỉ phía server.
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PreparedImage:
    content: bytes
    width: int
    height: int


def prepare_image(content: bytes) -> PreparedImage:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(415, "Chỉ hỗ trợ ảnh JPEG, PNG và WebP")
                if source.width * source.height > settings.IMAGE_MAX_PIXELS:
                    raise HTTPException(413, "Độ phân giải ảnh quá lớn")
                if getattr(source, "is_animated", False):
                    raise HTTPException(415, "Vui lòng dùng ảnh tĩnh")
                source.load()
                image = ImageOps.exif_transpose(source)
                image.thumbnail((1600, 1600))
                # Chỉ mã hoá lại điểm ảnh: bỏ EXIF/GPS và metadata không tin cậy.
                mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
                clean = Image.new(mode, image.size)
                clean.paste(image.convert(mode))
                output = BytesIO()
                clean.save(output, format="WEBP", quality=85, method=4)
                return PreparedImage(output.getvalue(), clean.width, clean.height)
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(413, "Độ phân giải ảnh quá lớn") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(422, "Tệp không phải ảnh hợp lệ hoặc đã bị hỏng") from exc


async def read_image(file: UploadFile) -> PreparedImage:
    try:
        if file.size is not None and file.size > settings.IMAGE_MAX_BYTES:
            raise HTTPException(413, "Ảnh vượt quá dung lượng cho phép")
        content = await file.read(settings.IMAGE_MAX_BYTES + 1)
        if len(content) > settings.IMAGE_MAX_BYTES:
            raise HTTPException(413, "Ảnh vượt quá dung lượng cho phép")
        return await run_in_threadpool(prepare_image, content)
    finally:
        await file.close()


class CloudinaryImages:
    def __init__(self):
        if not all((settings.CLOUDINARY_CLOUD_NAME, settings.CLOUDINARY_API_KEY, settings.CLOUDINARY_API_SECRET)):
            raise HTTPException(503, "Chưa cấu hình Cloudinary trên máy chủ")
        self.cloud_name = settings.CLOUDINARY_CLOUD_NAME
        self.auth = (settings.CLOUDINARY_API_KEY.get_secret_value(), settings.CLOUDINARY_API_SECRET.get_secret_value())
        self.base_url = f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image"

    async def _request(self, action, *, data, files=None):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10)) as client:
                response = await client.post(f"{self.base_url}/{action}", auth=self.auth, data=data, files=files)
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError("Invalid response")
                return result
        except (httpx.HTTPError, ValueError) as exc:
            # Không làm lộ body phản hồi hay thông tin xác thực của nhà cung cấp ra client/log.
            raise HTTPException(502, "Không thể lưu ảnh trên Cloudinary; vui lòng thử lại") from exc

    @observed('cloudinary.upload', 'tool', output=False)
    async def upload(self, image: PreparedImage, public_id: str) -> str:
        result = await self._request("upload", data={"public_id": public_id, "overwrite": "false"},
                                     files={"file": ("image.webp", image.content, "image/webp")})
        url = result.get("secure_url", "")
        if result.get("public_id") != public_id or not isinstance(url, str) or not url.startswith(
            f"https://res.cloudinary.com/{self.cloud_name}/image/upload/"
        ):
            raise HTTPException(502, "Cloudinary trả về thông tin ảnh không hợp lệ")
        return url

    @observed('cloudinary.destroy', 'tool', output=False)
    async def destroy(self, public_id: str):
        result = await self._request("destroy", data={"public_id": public_id, "invalidate": "true"})
        if result.get("result") not in {"ok", "not found"}:
            raise HTTPException(502, "Chưa thể xóa ảnh trên Cloudinary")


# --------------------------------------------------------------------------------------------------
# Chạy một lần bằng `python -m domains.media.services`; lên lịch vài phút một lần.
# --------------------------------------------------------------------------------------------------

logger = logging.getLogger(__name__)


async def cleanup_images(limit=50):
    cloud = CloudinaryImages()
    removed = 0
    for _ in range(limit):
        async with get_db_session() as session:
            ticket = await session.scalar(select(ImageCleanup).where(
                ImageCleanup.available_at <= datetime.now(timezone.utc),
                ImageCleanup.cloud_name == cloud.cloud_name,
            ).order_by(ImageCleanup.available_at).limit(1).with_for_update(skip_locked=True))
            if ticket is None:
                break
            # Bảo vệ mọi tài sản đang được gắn, kể cả ảnh chụp lịch sử không còn hoạt động.
            attached = False
            for model in MODELS.values():
                if await session.scalar(select(model.id).where(model.image_public_id == ticket.public_id).limit(1)):
                    attached = True
                    break
            if attached:
                await session.delete(ticket)
                continue
            try:
                await cloud.destroy(ticket.public_id)
            except Exception:
                ticket.available_at = datetime.now(timezone.utc) + timedelta(minutes=10)
                logger.warning("Cloudinary cleanup deferred for public_id=%s", ticket.public_id)
            else:
                await session.delete(ticket)
                removed += 1
    return removed


async def main():
    try:
        print(f"Removed {await cleanup_images()} unused images")
    finally:
        await close_crud_db_pool()


async def cleanup_loop():
    """Mỗi worker API đều có thể chạy hàm này; SKIP LOCKED phân phối việc dọn dẹp an toàn."""
    while True:
        try:
            await cleanup_images()
        except Exception:
            logger.warning("Image cleanup unavailable; retrying in five minutes")
        await asyncio.sleep(300)



# --------------------------------------------------------------------------------------------------
# Mỗi thực thể một ảnh bìa; khoá lạc quan và phiếu dọn dẹp bền vững.
# --------------------------------------------------------------------------------------------------

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
            # URL được quản lý mang tên cloud gốc của nó; không bao giờ xoá URL tuỳ ý.
            parsed = urlparse(entity.image_url or "")
            old_cloud = parsed.path.split("/")[1] if parsed.netloc == "res.cloudinary.com" else cloud_name
            await self.session.execute(insert(ImageCleanup).values(
                public_id=entity.image_public_id, cloud_name=old_cloud,
            ).on_conflict_do_nothing())

    async def upload(self, kind, entity_id, expected_version_id, file):
        entity = await self.entity(kind, entity_id, write=True)
        require_version(entity, expected_version_id)
        cloud = CloudinaryImages()  # thất bại sớm khi chưa cấu hình kho lưu trữ
        return await self._store(kind, entity_id, expected_version_id, await read_image(file), cloud)

    async def import_remote(self, kind, entity_id, expected_version_id, source_url):
        """Ảnh minh hoạ từ tra cứu được chọn trên thẻ xác nhận, lưu lại trên Cloudinary."""
        entity = await self.entity(kind, entity_id, write=True)
        require_version(entity, expected_version_id)
        cloud = CloudinaryImages()
        return await self._store(kind, entity_id, expected_version_id, await fetch_remote_image(source_url), cloud)

    async def _store(self, kind, entity_id, expected_version_id, image, cloud):
        public_id = f"{settings.CLOUDINARY_FOLDER}/{kind}/{entity_id}/{uuid4().hex}"
        # Commit phiếu dọn dẹp TRƯỚC I/O mạng. Sập hay lỗi DB sau đó
        # vẫn để lại phiếu bền vững; worker chờ một giờ cho các request đang dở.
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


# --------------------------------------------------------------------------------------------------
# Tải ảnh từ tra cứu để nhập lên Cloudinary mà không để server chạm tới mạng riêng.
# --------------------------------------------------------------------------------------------------

MAX_REDIRECTS = 3


def _https(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, "Địa chỉ ảnh phải là https công khai")
    return parsed


async def _public_address(host: str, port: int) -> str:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(422, "Không truy cập được địa chỉ ảnh") from exc
    addresses = sorted({info[4][0] for info in infos})
    # Mọi địa chỉ phân giải được đều phải là công khai: một câu trả lời lẫn lộn vẫn có thể tới host nội bộ.
    if not addresses or any(not ipaddress.ip_address(address.split("%")[0]).is_global for address in addresses):
        raise HTTPException(422, "Địa chỉ ảnh không hợp lệ")
    return addresses[0]


async def fetch_remote_image(url: str) -> PreparedImage:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False,
                                 headers={"User-Agent": "HercFit-ImageImport/1.0", "Accept": "image/*"}) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            parsed = _https(url)
            port = parsed.port or 443
            address = await _public_address(parsed.hostname, port)
            pinned = parsed._replace(netloc=f"[{address}]:{port}" if ":" in address else f"{address}:{port}").geturl()
            # Kết nối tới địa chỉ đã kiểm tra (chống DNS rebinding); SNI và kiểm tra chứng chỉ dùng hostname.
            request = client.build_request("GET", pinned, headers={"Host": parsed.netloc},
                                           extensions={"sni_hostname": parsed.hostname})
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise HTTPException(422, "Không tải được ảnh nguồn") from exc
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise HTTPException(422, "Không tải được ảnh nguồn")
                    url = urljoin(url, location)
                    continue
                if response.status_code != 200:
                    raise HTTPException(422, "Không tải được ảnh nguồn")
                if not response.headers.get("content-type", "").lower().startswith("image/"):
                    raise HTTPException(415, "Địa chỉ không trỏ tới một ảnh")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > settings.IMAGE_MAX_BYTES:
                    raise HTTPException(413, "Ảnh vượt quá dung lượng cho phép")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > settings.IMAGE_MAX_BYTES:
                        raise HTTPException(413, "Ảnh vượt quá dung lượng cho phép")
            except httpx.HTTPError as exc:
                raise HTTPException(422, "Không tải được ảnh nguồn") from exc
            finally:
                await response.aclose()
            # Cùng bước giải mã/mã hoá lại như ảnh người dùng tải lên: kiểm tra định dạng, bỏ EXIF, WebP.
            return await run_in_threadpool(prepare_image, bytes(body))
    raise HTTPException(422, "Ảnh nguồn chuyển hướng quá nhiều lần")


if __name__ == "__main__":
    asyncio.run(main())
