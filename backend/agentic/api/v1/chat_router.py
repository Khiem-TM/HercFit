"""V1 Chat & Agent orchestration endpoints."""

import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.dependencies import (
    get_optional_auth_token,
    get_short_term_memory,
    get_workflow_graph,
)
from core.llm import AIMessage, HumanMessage, RunnableConfig, get_tracing_callbacks
from graph.workflow import CompiledStateGraph
from memory.short_term import ShortTermMemory
from schemas.request import ChatRequest
from schemas.response import ChatHistoryResponse, ChatResponse

router = APIRouter(prefix="/chat", tags=["agent-chat"])


@router.post("", response_model=ChatResponse, summary="Invoke Multi-Agent Chat Workflow")
async def chat_invoke(
    payload: ChatRequest,
    graph: Annotated[CompiledStateGraph, Depends(get_workflow_graph)],
    short_memory: Annotated[ShortTermMemory, Depends(get_short_term_memory)],
    auth_token: Annotated[str | None, Depends(get_optional_auth_token)] = None,
) -> ChatResponse:
    run_id = str(uuid4())
    session_id = payload.session_id

    short_memory.append_user_text(session_id, payload.message)
    config = RunnableConfig(
        configurable={"thread_id": session_id, "user_id": payload.user_id or "anonymous"},
        callbacks=get_tracing_callbacks(),
    )
    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content=payload.message)],
        "user_id": payload.user_id,
        "session_id": session_id,
        "auth_token": auth_token,
        "iteration_count": 0,
        "tool_outputs": [],
        "context": dict(payload.metadata),
    }

    result_state = await graph.ainvoke(initial_state, config=config)
    messages = result_state.get("messages") or []
    last_ai_msg = next(
        (m for m in reversed(messages) if isinstance(m, AIMessage) or getattr(m, "type", "") == "ai"),
        None,
    )
    reply_text = str(last_ai_msg.content) if last_ai_msg else ""
    agent_used = getattr(last_ai_msg, "name", None) or "router_agent"

    if last_ai_msg is not None:
        short_memory.append_message(session_id, last_ai_msg)

    return ChatResponse(
        session_id=session_id,
        run_id=run_id,
        reply=reply_text,
        intent=result_state.get("intent"),
        agent_used=agent_used,
        tool_outputs=result_state.get("tool_outputs") or [],
        metadata={"reasoning": result_state.get("reasoning")},
    )


@router.post("/stream", summary="Stream Multi-Agent Chat Response (SSE)")
async def chat_stream(
    payload: ChatRequest,
    graph: Annotated[CompiledStateGraph, Depends(get_workflow_graph)],
    short_memory: Annotated[ShortTermMemory, Depends(get_short_term_memory)],
    auth_token: Annotated[str | None, Depends(get_optional_auth_token)] = None,
) -> StreamingResponse:
    run_id = str(uuid4())
    session_id = payload.session_id
    short_memory.append_user_text(session_id, payload.message)

    config = RunnableConfig(
        configurable={"thread_id": session_id, "user_id": payload.user_id or "anonymous"},
        callbacks=get_tracing_callbacks(),
    )
    initial_state: dict[str, Any] = {
        "messages": [HumanMessage(content=payload.message)],
        "user_id": payload.user_id,
        "session_id": session_id,
        "auth_token": auth_token,
        "iteration_count": 0,
        "tool_outputs": [],
        "context": dict(payload.metadata),
    }

    async def event_stream() -> AsyncGenerator[str, None]:
        async for update in graph.astream(initial_state, config=config, stream_mode="updates"):
            for node_name, node_state in update.items():
                node_msgs = (node_state or {}).get("messages") or []
                for msg in node_msgs:
                    if isinstance(msg, AIMessage):
                        short_memory.append_message(session_id, msg)
                        chunk = {
                            "type": "message",
                            "run_id": run_id,
                            "session_id": session_id,
                            "node": node_name,
                            "content": str(msg.content),
                        }
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get(
    "/history/{session_id}",
    response_model=ChatHistoryResponse,
    summary="Get Session Conversation History",
)
async def get_chat_history(
    session_id: str,
    short_memory: Annotated[ShortTermMemory, Depends(get_short_term_memory)],
) -> ChatHistoryResponse:
    summary = short_memory.to_summary_dict(session_id)
    return ChatHistoryResponse.model_validate(summary)


@router.delete(
    "/history/{session_id}",
    summary="Clear Session Conversation History",
)
async def clear_chat_history(
    session_id: str,
    short_memory: Annotated[ShortTermMemory, Depends(get_short_term_memory)],
) -> dict[str, str]:
    short_memory.clear_session(session_id)
    return {"status": "cleared", "session_id": session_id}
