"""Entrypoint script to start the FastAPI + LangGraph Agent & CRUD server."""

import uvicorn

from core.settings import settings

if __name__ == "__main__":
    uvicorn.run(
        "agents.service.service:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.MODE == "dev",
        timeout_graceful_shutdown=settings.GRACEFUL_SHUTDOWN_TIMEOUT,
    )

