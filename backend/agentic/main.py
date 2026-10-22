"""Run from backend/: python -m uvicorn agentic.main:app --port 8081."""
from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path
import sys

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from agentic.api.v1.chat_router import router
from agentic.config.settings import agent_settings
from agentic.core.llm import Models
from agentic.clients.backend_client import BackendClient
from agentic.clients.tavily import TavilyClient
from agentic.graph.checkpoints import persistence
from agentic.graph.workflow import build_workflow
from agentic.runtime import Runtime
from knowledge_graph.service import GraphContextService


def create_agentic_app(settings=agent_settings, *, models=None, tavily_client=None):
    @asynccontextmanager
    async def lifespan(app):
        settings.check()
        backend=BackendClient(settings.BACKEND_BASE_URL,settings.BACKEND_TIMEOUT_SECONDS)
        tavily_key=settings.TAVILY_API_KEY.get_secret_value() if settings.TAVILY_API_KEY else ''
        tavily=tavily_client or TavilyClient(tavily_key)
        try:
            async with persistence(settings) as (store,saver):
                app.state.backend=backend
                graph_context=GraphContextService(settings,store)
                app.state.graph_context=graph_context
                app.state.runtime=Runtime(build_workflow(models or Models(settings),store,saver,tavily,settings,
                                                        graph_context=graph_context),store,saver,settings)
                reconciler=asyncio.create_task(app.state.runtime.reconcile_forever())
                try:
                    yield
                finally:
                    reconciler.cancel()
                    await asyncio.gather(reconciler,return_exceptions=True)
                    await graph_context.close()
        finally:
            await backend.close()
            await tavily.close()
    app=FastAPI(title='HercFit Agentic',version='2.0.0',lifespan=lifespan)
    app.add_middleware(CORSMiddleware,allow_origins=settings.CORS_ORIGINS,allow_credentials=True,
                       allow_methods=['GET','POST','DELETE'],allow_headers=['Authorization','Content-Type'])
    app.include_router(router,prefix='/api/v1')
    @app.get('/health')
    async def health(): return {'status':'ok','service':'hercfit-agentic'}
    @app.get('/health/ready')
    async def ready():
        try:
            await app.state.runtime.store.ready()
            r=await app.state.backend.http.get('/health/ready')
            r.raise_for_status()
            return {'status':'ready','knowledge_graph_mode':settings.KG_MODE}
        except Exception:
            return JSONResponse({'status':'not_ready'},status_code=503)
    return app

app=create_agentic_app()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('agentic.main:app', host='0.0.0.0', port=agent_settings.AGENT_PORT, reload=agent_settings.MODE == 'dev')
