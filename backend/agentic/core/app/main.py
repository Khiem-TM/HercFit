"""Run from backend/: python -m uvicorn agentic.core.app.main:app --port 8081."""
from contextlib import AsyncExitStack, asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from agentic.core.app.api.v1.chat_router import router
from agentic.core.app.config import agent_settings
from agentic.core.llm import Models
from agentic.tools.integrations.backend_client import BackendClient
from agentic.tools.integrations.tavily import TavilyClient
from agentic.tools.integrations.jev import JevClient
from agentic.services.jev import JevService
from agentic.services.memory.checkpoints import persistence
from agentic.agents.workflow import build_workflow
from agentic.services.runtime import Runtime
from agentic.knowledge_graph.service import GraphContextService
from agentic.observability import observer
from agentic.observability.middleware import ObservabilityMiddleware


def create_agentic_app(settings=agent_settings, *, models=None, tavily_client=None, jev_client=None,
                       backend_client=None, persistence_factory=None, graph_context_factory=None):
    """Compose dependencies once per lifespan, including cleanup on partial startup.

    Injected clients follow the existing ownership contract: the app closes them.
    Factories make local tests possible without starting PostgreSQL or Neo4j.
    """
    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as resources:
            resources.push_async_callback(observer().close)
            settings.check()
            backend = backend_client if backend_client is not None else BackendClient(
                settings.BACKEND_BASE_URL, settings.BACKEND_TIMEOUT_SECONDS)
            resources.push_async_callback(backend.close)
            tavily_key = settings.TAVILY_API_KEY.get_secret_value() if settings.TAVILY_API_KEY else ''
            tavily = tavily_client if tavily_client is not None else TavilyClient(tavily_key)
            resources.push_async_callback(tavily.close)
            jev = jev_client
            if jev is None and getattr(settings, 'JEV_MODE', 'off') != 'off':
                jev = JevClient(settings)
            if jev is not None:
                resources.push_async_callback(jev.close)
            agent_models = models if models is not None else Models(settings)
            memory = None
            if getattr(settings, 'SESSION_MEMORY_MODE', 'off') != 'off':
                # Optional Redis failure falls back to authoritative checkpoints.
                from agentic.services.memory.session_memory import SessionMemory
                memory = SessionMemory.connect(settings, agent_models)
                resources.push_async_callback(memory.close)
                await memory.health()
            store, saver = await resources.enter_async_context((persistence_factory or persistence)(settings))
            app.state.backend = backend
            graph_context = (graph_context_factory or GraphContextService)(settings, store)
            resources.push_async_callback(graph_context.close)
            app.state.graph_context = graph_context
            jev_service = JevService(jev, store, settings) if jev is not None else None
            app.state.runtime = Runtime(
                build_workflow(agent_models, store, saver, tavily, settings,
                               graph_context=graph_context, jev=jev_service),
                store, saver, settings, memory)
            tasks = []
            try:
                tasks.append(asyncio.create_task(app.state.runtime.reconcile_forever()))
                tasks.append(asyncio.create_task(graph_context.warm_up()))
                yield
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    app=FastAPI(title='HercFit Agentic',version='2.0.0',lifespan=lifespan)
    app.add_middleware(ObservabilityMiddleware, service='agentic')
    app.add_middleware(CORSMiddleware,allow_origins=settings.CORS_ORIGINS,allow_credentials=True,
                       allow_methods=['GET','POST','DELETE'],allow_headers=['Authorization','Content-Type'],
                       expose_headers=['X-Request-ID','X-Trace-ID','Retry-After'])
    app.include_router(router,prefix='/api/v1')
    @app.get('/health')
    async def health(): return {'status':'ok','service':'hercfit-agentic'}
    @app.get('/health/ready')
    async def ready():
        try:
            await app.state.runtime.store.ready()
            r=await app.state.backend.http.get('/health/ready')
            r.raise_for_status()
            result={'status':'ready','knowledge_graph_mode':settings.KG_MODE,'observability':observer().status()}
            memory=getattr(app.state.runtime,'memory',None)
            if memory is not None:
                # Reported, never required: chat works without Redis.
                result['session_memory']=await memory.health()
            return result
        except Exception:
            return JSONResponse({'status':'not_ready'},status_code=503)
    return app

app=create_agentic_app()

def main():
    import uvicorn
    uvicorn.run('agentic.core.app.main:app', host='0.0.0.0', port=agent_settings.AGENT_PORT, reload=agent_settings.MODE == 'dev')


if __name__ == '__main__':
    main()
