"""Chạy từ backend/: python -m uvicorn agentic.core.app.main:app --port 8081."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentic.agents.workflow import build_workflow
from agentic.core.app.api.health import router as health_router
from agentic.core.app.api.v1.chat_router import router
from agentic.core.app.config import AgentSettings, agent_settings
from agentic.core.llm import Models
from agentic.knowledge_graph.service import GraphContextService
from agentic.observability import observer
from agentic.observability.middleware import ObservabilityMiddleware
from agentic.services.jev import JevService
from agentic.services.memory.checkpoints import persistence
from agentic.services.runtime import Runtime
from agentic.tools.integrations.backend_client import BackendClient
from agentic.tools.integrations.jev import JevClient
from agentic.tools.integrations.tavily import TavilyClient


async def create_session_memory(settings: AgentSettings, models, stack: AsyncExitStack):
    if settings.SESSION_MEMORY_MODE == "off":
        return None

    from agentic.services.memory.session_memory import SessionMemory

    memory = SessionMemory.connect(settings, models)
    stack.push_async_callback(memory.close)
    await memory.health()
    return memory


@asynccontextmanager
async def manage_background_tasks(runtime, graph_context, store, settings: AgentSettings):
    tasks = []
    try:
        tasks.append(asyncio.create_task(runtime.reconcile_forever()))
        # Store được tiêm cho evaluation có thể không dùng PostgreSQL.
        if settings.CONSENT_PURGE_ENABLED and hasattr(store, "pool"):
            from agentic.services.consent_purge import purge_forever

            tasks.append(asyncio.create_task(purge_forever(runtime)))
        if graph_context is not None:
            tasks.append(asyncio.create_task(graph_context.warm_up()))
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def create_agentic_app(
    settings: AgentSettings = agent_settings,
    *,
    models=None,
    tavily_client=None,
    jev_client=None,
    backend_client=None,
    persistence_factory=None,
    graph_context_factory=None,
) -> FastAPI:
    """Dựng dependency theo vòng đời app; app cũng đóng các client được tiêm vào."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            stack.push_async_callback(observer().close)
            settings.check()

            service_secret = (
                settings.AGENT_SERVICE_SECRET.get_secret_value()
                if settings.AGENT_SERVICE_SECRET
                else None
            )
            backend = (
                backend_client
                if backend_client is not None
                else BackendClient(
                    settings.BACKEND_BASE_URL,
                    settings.BACKEND_TIMEOUT_SECONDS,
                    **({"service_secret": service_secret} if service_secret else {}),
                )
            )
            stack.push_async_callback(backend.close)

            tavily_key = (
                settings.TAVILY_API_KEY.get_secret_value() if settings.TAVILY_API_KEY else ""
            )
            tavily = tavily_client if tavily_client is not None else TavilyClient(tavily_key)
            stack.push_async_callback(tavily.close)

            jev = jev_client
            if jev is None and settings.JEV_MODE != "off":
                jev = JevClient(settings)
            if jev is not None:
                stack.push_async_callback(jev.close)

            agent_models = models if models is not None else Models(settings)
            memory = await create_session_memory(settings, agent_models, stack)
            store, saver = await stack.enter_async_context(
                (persistence_factory or persistence)(settings)
            )

            # Chỉ baseline evaluation mới dùng factory trả về None.
            graph_context = (graph_context_factory or GraphContextService)(settings, store)
            if graph_context is not None:
                stack.push_async_callback(graph_context.close)
            jev_service = JevService(jev, store, settings) if jev is not None else None
            workflow = build_workflow(
                agent_models,
                store,
                saver,
                tavily,
                settings,
                graph_context=graph_context,
                jev=jev_service,
            )
            runtime = Runtime(workflow, store, saver, settings, memory)

            app.state.backend = backend
            app.state.graph_context = graph_context
            app.state.runtime = runtime
            async with manage_background_tasks(runtime, graph_context, store, settings):
                yield

    app = FastAPI(title="HercFit Agentic", version="2.0.0", lifespan=lifespan)
    app.add_middleware(ObservabilityMiddleware, service="agentic")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID", "X-Trace-ID", "Retry-After"],
    )
    app.include_router(router, prefix="/api/v1")
    app.include_router(health_router)
    return app


app = create_agentic_app()


def main():
    import uvicorn

    uvicorn.run(
        "agentic.core.app.main:app",
        host="0.0.0.0",
        port=agent_settings.AGENT_PORT,
        reload=agent_settings.MODE == "dev",
    )


if __name__ == "__main__":
    main()
