"""Lệnh ghi nghiệp vụ idempotent, commit nguyên tử cùng phản hồi của chúng."""

import json
from contextvars import ContextVar
from hashlib import sha256

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import TypeAdapter
from sqlalchemy import text

active_request: ContextVar[Request | None] = ContextVar("idempotency_request", default=None)


class IdempotentRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request: Request):
            # Cache body trên cùng Request mà FastAPI sẽ kiểm tra.
            await request.body()
            token = active_request.set(request)
            try:
                return await handler(request)
            finally:
                active_request.reset(token)

        return wrapped


async def execute_idempotent(request, service, invoke, response):
    key = request.headers.get("Idempotency-Key")
    if not key or request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return await invoke()
    # Vô hiệu hoá tài khoản cố ý nằm ngoài hợp đồng ghi của agent.
    if request.url.path == "/api/profile" and request.method == "DELETE":
        return await invoke()
    if len(key) > 128 or not key.isascii() or not key.isprintable():
        raise HTTPException(422, "Invalid Idempotency-Key")
    session, user_id = service.session, str(service.user_id)
    raw = await request.body()
    body = json.loads(raw) if raw else None
    digest = sha256(json.dumps(
        [request.method, request.url.path, sorted(request.query_params.multi_items()), body],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    # Khoá kể cả khi dòng sổ chưa tồn tại. Cùng người dùng/khoá được tuần tự hoá
    # giữa các tiến trình; rollback nhả khoá và không để lại thành công ảo.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                          {"key": f"idempotency:{user_id}:{key}"})
    stored = (await session.execute(text(
        "SELECT request_hash, status_code, body, headers FROM api_idempotency "
        "WHERE user_id = CAST(:user_id AS uuid) AND key = :key"
    ), {"user_id": user_id, "key": key})).mappings().first()
    if stored:
        if stored["request_hash"] != digest:
            raise HTTPException(409, "Idempotency-Key already used for a different request")
        return replay(stored["status_code"], stored["body"], stored["headers"])
    result = await invoke()
    route = request.scope["route"]
    if isinstance(result, Response):
        status_code = result.status_code
        content = json.loads(result.body) if result.body else None
        headers = {k: v for k, v in result.headers.items() if k.lower() == "location"}
    else:
        adapter = TypeAdapter(route.response_model)
        value = adapter.validate_python(result, from_attributes=True)
        content = adapter.dump_python(value, mode="json")
        status_code = route.status_code or 200
        headers = {"location": response.headers["location"]} if response and "location" in response.headers else {}
    await session.execute(text(
        "INSERT INTO api_idempotency (user_id, key, request_hash, status_code, body, headers) "
        "VALUES (CAST(:user_id AS uuid), :key, :digest, :status, CAST(:body AS jsonb), CAST(:headers AS jsonb))"
    ), {"user_id": user_id, "key": key, "digest": digest, "status": status_code,
        "body": json.dumps(content), "headers": json.dumps(headers)})
    return replay(status_code, content, headers)


async def prune(session, days: int) -> int:
    """Xoá dòng sổ idempotency cũ hơn `days` ngày (client chỉ thử lại trong vài phút); trả về số dòng đã xoá."""
    result = await session.execute(text(
        "DELETE FROM api_idempotency WHERE created_at < now() - make_interval(days => :days)"
    ), {"days": days})
    return result.rowcount or 0


def replay(status, body, headers):
    if status == 204:
        return Response(status_code=204, headers=headers)
    return JSONResponse(body, status_code=status, headers=headers)
