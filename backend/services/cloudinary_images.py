"""Bounded image decoding and authenticated, server-only Cloudinary requests."""
from observability import observed
from dataclasses import dataclass
from io import BytesIO
import warnings

import httpx
from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from core.settings import settings


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
                # Re-encode pixels only: strips EXIF/GPS and untrusted metadata.
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
            # Do not leak provider response bodies or credentials to clients/logs.
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
