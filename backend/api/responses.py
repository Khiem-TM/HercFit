"""Hàm hỗ trợ response dùng chung cho các endpoint aggregate có phiên bản."""

from fastapi import Response
from fastapi.responses import JSONResponse


def created(response: Response, resource: str, entity):
    response.headers["Location"] = f"/api/{resource}/{entity.id}"
    return entity


def current_or_not_found(entity, name: str):
    # Trả về một response cho phép @transaction commit việc hết hạn trước khi gửi 404.
    return entity if entity is not None else JSONResponse(status_code=404, content={"detail": f"{name} not found"})
