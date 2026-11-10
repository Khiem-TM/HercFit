import asyncio
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agentic.core.app.dependencies import authenticated
from agentic.core.app.schemas.request import ChatRequest, ConfirmationRequest, FoodNutritionRequest
from agentic.core.app.schemas.response import ChatResponse, FoodNutrition
from agentic.core.context import request_context
from agentic.observability.outcomes import CANCELLED, DISCONNECT, FAILED, ChatSession, note_error
from agentic.security.input_guard import safe_query
from agentic.services import nutrition_lookup
from core.rate_limit import SlidingWindowLimiter

router = APIRouter(prefix="/chat", tags=["agent-chat"])
_limiters = {}


def _limiter(request: Request):
    limit = request.app.state.runtime.settings.AGENT_RATE_LIMIT_PER_MINUTE
    limiter = _limiters.get(limit)
    if limiter is None:
        limiter = _limiters[limit] = SlidingWindowLimiter(limit)
    return limiter


async def rate_limited(request: Request, ctx=Depends(authenticated)):
    """Giới hạn dồn dập theo từng người dùng cho các endpoint có gọi model (theo từng tiến trình)."""
    wait = _limiter(request).check(ctx.user_id)
    if wait is not None:
        raise HTTPException(
            429,
            "Bạn gửi yêu cầu quá nhanh, vui lòng thử lại sau ít giây.",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    return ctx


async def new_turn(request: Request, ctx=Depends(rate_limited)):
    """Ngân sách theo ngày bền vững, dùng chung cho mọi worker (OWASP LLM10: tiêu thụ không giới hạn)."""
    runtime = request.app.state.runtime
    settings = runtime.settings
    if not await runtime.store.consume_turn(
        ctx.user_id,
        turn_limit=settings.AGENT_DAILY_TURN_LIMIT,
        token_limit=settings.AGENT_DAILY_TOKEN_LIMIT,
    ):
        raise HTTPException(
            429, "Bạn đã dùng hết hạn mức trò chuyện hôm nay. Hạn mức sẽ được làm mới vào ngày mai."
        )
    return ctx


async def _tracked(session, call):
    """Một kết cục cuối cho lượt chat không stream: theo trạng thái ChatResponse, không theo mã HTTP."""
    with session:
        try:
            result = await call
        except HTTPException as exc:
            session.finish(FAILED, status_code=exc.status_code)
            raise
        session.finish_result(result.status)
        return result


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, ctx=Depends(new_turn)):
    return await _tracked(
        ChatSession("chat", payload.mode), request.app.state.runtime.chat(payload, ctx.user_id)
    )


@router.post("/confirm", response_model=ChatResponse)
async def confirm(payload: ConfirmationRequest, request: Request, ctx=Depends(rate_limited)):
    return await _tracked(
        ChatSession("confirm"), request.app.state.runtime.confirm(payload, ctx.user_id)
    )


# Mô tả tường minh: văn bản mặc định lấy từ http.HTTPStatus và khác nhau giữa Python 3.12 và 3.13.
NUTRITION_RESPONSES = {
    404: {"description": "No trustworthy figures found"},
    422: {"description": "Not a food name"},
    503: {"description": "Suggestion temporarily unavailable"},
}


@router.post("/food-nutrition", response_model=FoodNutrition, responses=NUTRITION_RESPONSES)
async def food_nutrition(
    payload: FoodNutritionRequest, request: Request, ctx=Depends(rate_limited)
):
    """Nút gợi ý trên thẻ tạo món riêng: 4 chỉ số trên 100 g từ một truy vấn web, hoặc 404 để người dùng tự nhập."""
    try:
        name = safe_query(payload.name)
    except ValueError:
        raise HTTPException(422, "Chỉ nhập tên món ăn.")
    try:
        facts = await nutrition_lookup.suggest(
            request.app.state.models, request.app.state.tavily, name
        )
    except nutrition_lookup.NutritionUnavailable:
        raise HTTPException(
            503, "Gợi ý dinh dưỡng tạm thời không khả dụng; bạn nhập số liệu giúp nhé."
        )
    if facts is None:
        raise HTTPException(
            404, "Chưa tìm được số liệu đáng tin cho món này; bạn nhập số liệu giúp nhé."
        )
    return facts


@router.post("/stream")
async def stream(payload: ChatRequest, request: Request, ctx=Depends(new_turn)):
    heartbeat = request.app.state.runtime.settings.SSE_HEARTBEAT_SECONDS

    async def events():
        queue = asyncio.Queue()
        # Kết cục cuối chỉ được ghi khi sự kiện cuối thật sự đã gửi xong cho client (sau `yield`).
        session = ChatSession("stream", payload.mode)
        final = {}

        async def produce():
            mark = request_context.set(ctx)
            try:
                result = await request.app.state.runtime.chat(payload, ctx.user_id, queue.put)
                event = {
                    "completed": "message",
                    "needs_input": "needs_input",
                    "pending_confirmation": "pending_confirmation",
                    "failed": "error",
                }[result.status]
                final["status"] = result.status
                await queue.put({"type": event, **result.model_dump(mode="json")})
            except HTTPException as exc:
                final["status_code"] = exc.status_code
                await queue.put(
                    {"type": "error", "status_code": exc.status_code, "detail": exc.detail}
                )
            except Exception as exc:
                note_error(exc)
                final["error"] = exc
                await queue.put({"type": "error", "detail": "Agent service failed"})
            finally:
                request_context.reset(mark)
                await queue.put(None)

        def settle():
            if "status" in final:
                session.finish_result(final["status"])
            elif "status_code" in final:
                session.finish(FAILED, status_code=final["status_code"])
            elif "error" in final:
                session.finish(FAILED, error=final["error"])

        with session:
            task = asyncio.create_task(produce())
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                    except TimeoutError:
                        if await request.is_disconnected():
                            # Client đã rời đi; dừng lượt chạy thay vì tính toán cho không ai cả.
                            session.finish(CANCELLED, failure_class=DISCONNECT)
                            break
                        # Comment SSE: giữ cho proxy không đóng một kết nối đang im lặng.
                        yield ": ping\n\n"
                        continue
                    if item is None:
                        settle()
                        break
                    yield "data: " + json.dumps(item, ensure_ascii=False) + "\n\n"
                    if item.get("type") == "token":
                        session.first_token()
                    elif item.get("type") != "progress":
                        settle()
                yield "data: [DONE]\n\n"
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions")
async def sessions(request: Request, ctx=Depends(authenticated)):
    return await request.app.state.runtime.sessions(ctx.user_id)


@router.get("/history/{session_id}")
async def history(session_id: str, request: Request, ctx=Depends(authenticated)):
    return await request.app.state.runtime.history(session_id, ctx.user_id)


@router.delete("/history/{session_id}")
async def clear(session_id: str, request: Request, ctx=Depends(authenticated)):
    return await request.app.state.runtime.clear(session_id, ctx.user_id)


@router.delete("/me", summary="Xoá toàn bộ hội thoại và bộ nhớ của người dùng (quyền xoá dữ liệu)")
async def purge_me(request: Request, ctx=Depends(authenticated)):
    return await request.app.state.runtime.purge_user(ctx.user_id)


@router.get("/knowledge-graph")
async def knowledge_graph(
    request: Request, start: date | None = None, end: date | None = None, ctx=Depends(authenticated)
):
    """Bản đồ cá nhân; `start`/`end` là các ngày địa phương (tính cả hai đầu) giới hạn những bản ghi được vẽ."""
    if start and end and start > end:
        raise HTTPException(422, "start must not be after end")
    from agentic.knowledge_graph.visualization import personal_graph

    return await personal_graph(request.app.state.graph_context, ctx.user_id, start=start, end=end)
