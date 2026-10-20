"""Response helpers shared by versioned aggregate endpoints."""

from fastapi import Response
from fastapi.responses import JSONResponse


def created(response: Response, resource: str, entity):
    response.headers["Location"] = f"/api/{resource}/{entity.id}"
    return entity


def current_or_not_found(entity, name: str):
    # A returned response allows @transaction to commit expiry before sending 404.
    return entity if entity is not None else JSONResponse(status_code=404, content={"detail": f"{name} not found"})
