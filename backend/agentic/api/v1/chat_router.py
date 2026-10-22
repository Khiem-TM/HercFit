import asyncio
import json
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse
from agentic.api.dependencies import authenticated
from agentic.schemas.request import ChatRequest, ConfirmationRequest
from agentic.schemas.response import ChatResponse
from agentic.core.context import request_context

router=APIRouter(prefix='/chat',tags=['agent-chat'])

@router.post('',response_model=ChatResponse)
async def chat(payload:ChatRequest,request:Request,ctx=Depends(authenticated)):
    return await request.app.state.runtime.chat(payload,ctx.user_id)

@router.post('/confirm',response_model=ChatResponse)
async def confirm(payload:ConfirmationRequest,request:Request,ctx=Depends(authenticated)):
    return await request.app.state.runtime.confirm(payload,ctx.user_id)

@router.post('/stream')
async def stream(payload:ChatRequest,request:Request,ctx=Depends(authenticated)):
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
                item=await queue.get()
                if item is None: break
                yield 'data: '+json.dumps(item,ensure_ascii=False)+'\n\n'
            yield 'data: [DONE]\n\n'
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})

@router.get('/sessions')
async def sessions(request:Request,ctx=Depends(authenticated)):
    return await request.app.state.runtime.sessions(ctx.user_id)

@router.get('/history/{session_id}')
async def history(session_id:str,request:Request,ctx=Depends(authenticated)):
    return await request.app.state.runtime.history(session_id,ctx.user_id)

@router.delete('/history/{session_id}')
async def clear(session_id:str,request:Request,ctx=Depends(authenticated)):
    return await request.app.state.runtime.clear(session_id,ctx.user_id)
