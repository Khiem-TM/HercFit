import asyncio
import json
from datetime import date
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from agentic.core.app.dependencies import authenticated
from agentic.core.app.schemas.request import ChatRequest, ConfirmationRequest
from agentic.core.app.schemas.response import ChatResponse
from agentic.core.context import request_context
from core.rate_limit import SlidingWindowLimiter

router=APIRouter(prefix='/chat',tags=['agent-chat'])
_limiters = {}


def _settings(request: Request):
    # Lightweight runtimes (tests, tools) may omit settings; callers fall back to defaults.
    return getattr(request.app.state.runtime, 'settings', None)


def _limiter(request: Request):
    settings = _settings(request)
    limit = getattr(settings, 'AGENT_RATE_LIMIT_PER_MINUTE', 20)
    limiter = _limiters.get(limit)
    if limiter is None:
        limiter = _limiters[limit] = SlidingWindowLimiter(limit)
    return limiter


async def rate_limited(request: Request, ctx=Depends(authenticated)):
    """Per-user burst limit for model-backed endpoints (per process)."""
    wait = _limiter(request).check(ctx.user_id)
    if wait is not None:
        raise HTTPException(429, 'Bạn gửi yêu cầu quá nhanh, vui lòng thử lại sau ít giây.',
                            headers={'Retry-After': str(int(wait) + 1)})
    return ctx


async def new_turn(request: Request, ctx=Depends(rate_limited)):
    """Durable daily budget shared by all workers (OWASP LLM10: unbounded consumption)."""
    runtime = request.app.state.runtime
    settings = _settings(request)
    consume = getattr(getattr(runtime, 'store', None), 'consume_turn', None)
    if consume and not await consume(ctx.user_id, turn_limit=getattr(settings, 'AGENT_DAILY_TURN_LIMIT', 0),
                                     token_limit=getattr(settings, 'AGENT_DAILY_TOKEN_LIMIT', 0)):
        raise HTTPException(429, 'Bạn đã dùng hết hạn mức trò chuyện hôm nay. Hạn mức sẽ được làm mới vào ngày mai.')
    return ctx


@router.post('',response_model=ChatResponse)
async def chat(payload:ChatRequest,request:Request,ctx=Depends(new_turn)):
    return await request.app.state.runtime.chat(payload,ctx.user_id)

@router.post('/confirm',response_model=ChatResponse)
async def confirm(payload:ConfirmationRequest,request:Request,ctx=Depends(rate_limited)):
    return await request.app.state.runtime.confirm(payload,ctx.user_id)

@router.post('/stream')
async def stream(payload:ChatRequest,request:Request,ctx=Depends(new_turn)):
    heartbeat = getattr(_settings(request), 'SSE_HEARTBEAT_SECONDS', 15)

    async def events():
        queue=asyncio.Queue()
        async def produce():
            mark=request_context.set(ctx)
            try:
                result=await request.app.state.runtime.chat(payload,ctx.user_id,queue.put)
                event={'completed':'message','needs_input':'needs_input','pending_confirmation':'pending_confirmation','failed':'error'}[result.status]
                await queue.put({'type':event,**result.model_dump(mode='json')})
            except HTTPException as exc:
                await queue.put({'type':'error','status_code':exc.status_code,'detail':exc.detail})
            except Exception:
                await queue.put({'type':'error','detail':'Agent service failed'})
            finally:
                request_context.reset(mark)
                await queue.put(None)
        task=asyncio.create_task(produce())
        try:
            while True:
                try:
                    item=await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except (asyncio.TimeoutError, TimeoutError):
                    if await request.is_disconnected():
                        break  # The client left; stop the run instead of computing for nobody.
                    # SSE comment: keeps proxies from closing a quiet connection.
                    yield ': ping\n\n'
                    continue
                if item is None: break
                yield 'data: '+json.dumps(item,ensure_ascii=False)+'\n\n'
            yield 'data: [DONE]\n\n'
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    return StreamingResponse(events(),media_type='text/event-stream',
                             headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@router.get('/sessions')
async def sessions(request:Request,ctx=Depends(authenticated)):
    return await request.app.state.runtime.sessions(ctx.user_id)

@router.get('/history/{session_id}')
async def history(session_id:str,request:Request,ctx=Depends(authenticated)):
    return await request.app.state.runtime.history(session_id,ctx.user_id)

@router.delete('/history/{session_id}')
async def clear(session_id:str,request:Request,ctx=Depends(authenticated)):
    return await request.app.state.runtime.clear(session_id,ctx.user_id)

@router.delete('/me', summary='Xoá toàn bộ hội thoại và bộ nhớ của người dùng (quyền xoá dữ liệu)')
async def purge_me(request:Request,ctx=Depends(authenticated)):
    return await request.app.state.runtime.purge_user(ctx.user_id)

@router.get('/knowledge-graph')
async def knowledge_graph(request:Request,start:date|None=None,end:date|None=None,ctx=Depends(authenticated)):
    """Personal map; `start`/`end` are inclusive local days that limit which records it draws."""
    if start and end and start>end:
        raise HTTPException(422,'start must not be after end')
    from knowledge_graph.visualization import personal_graph
    return await personal_graph(request.app.state.graph_context,ctx.user_id,start=start,end=end)
