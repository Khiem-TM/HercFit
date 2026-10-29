"""Fetch a research picture for Cloudinary import without letting the server reach private networks."""
import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from core.settings import settings
from services.cloudinary_images import PreparedImage, prepare_image

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
    # Every resolved address must be public: a mixed answer could still reach an internal host.
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
            # Connect to the vetted address (no DNS rebinding); SNI and certificate checks use the hostname.
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
            # Same decoding/re-encoding as user uploads: format check, EXIF strip, WebP.
            return await run_in_threadpool(prepare_image, bytes(body))
    raise HTTPException(422, "Ảnh nguồn chuyển hướng quá nhiều lần")
