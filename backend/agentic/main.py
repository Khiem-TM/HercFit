"""Entry point for starting the HercFit Agentic API Server."""

from contextlib import asynccontextmanager
import sys
from pathlib import Path

_CURRENT_DIR = str(Path(__file__).resolve().parent)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from api.dependencies import get_backend_client, get_checkpoint_manager
from api.v1.chat_router import router as chat_router
from config.settings import agent_settings
from core.exceptions import AgenticBaseError
from graph.workflow import compile_agent_workflow
from schemas.response import AgentHealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent_settings.validate_agent_configuration()
    backend_client = get_backend_client()
    checkpoint_mgr = get_checkpoint_manager()
    async with checkpoint_mgr.lifespan_saver() as saver:
        app.state.workflow_graph = compile_agent_workflow(
            checkpointer=saver,
            backend_client=backend_client,
        )
        try:
            yield
        finally:
            await backend_client.close()


def create_agentic_app() -> FastAPI:
    app = FastAPI(
        title="HercFit Agentic Service",
        version="1.0.0",
        description="Multi-Agent AI Orchestration Service for HercFit Fitness & Nutrition.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=agent_settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.exception_handler(AgenticBaseError)
    async def handle_agentic_error(_request: Request, exc: AgenticBaseError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.get("/health", response_model=AgentHealthResponse, tags=["health"])
    async def health() -> AgentHealthResponse:
        return AgentHealthResponse(
            status="ok",
            service="hercfit-agentic",
            default_model=agent_settings.DEFAULT_MODEL,
            fake_model_enabled=agent_settings.USE_FAKE_MODEL,
            checkpoint_backend=str(agent_settings.CHECKPOINT_BACKEND),
        )

    app.include_router(chat_router, prefix="/api/v1")
    return app


app = create_agentic_app()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=agent_settings.AGENT_HOST,
        port=agent_settings.AGENT_PORT,
        reload=agent_settings.is_dev(),
        timeout_graceful_shutdown=agent_settings.GRACEFUL_SHUTDOWN_TIMEOUT,
    )

