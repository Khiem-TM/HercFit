"""FastAPI Dependency Injection providers for Auth, BackendClient pool, Memory, and Workflow Graph."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from clients.backend_client import BackendClient
from config.settings import agent_settings
from graph.checkpoints import CheckpointManager
from graph.workflow import CompiledStateGraph, compile_agent_workflow
from memory.long_term import LongTermMemory
from memory.short_term import ShortTermMemory
from tools.definitions.backend_tools import set_shared_backend_client

_bearer_scheme = HTTPBearer(auto_error=False)

_backend_client_singleton: BackendClient | None = None
_checkpoint_manager_singleton: CheckpointManager | None = None
_short_term_memory_singleton: ShortTermMemory | None = None
_long_term_memory_singleton: LongTermMemory | None = None
_compiled_graph_singleton: CompiledStateGraph | None = None


def get_backend_client() -> BackendClient:
    global _backend_client_singleton
    if _backend_client_singleton is None:
        _backend_client_singleton = BackendClient()
        set_shared_backend_client(_backend_client_singleton)
    return _backend_client_singleton


def get_checkpoint_manager() -> CheckpointManager:
    global _checkpoint_manager_singleton
    if _checkpoint_manager_singleton is None:
        _checkpoint_manager_singleton = CheckpointManager()
    return _checkpoint_manager_singleton


def get_short_term_memory() -> ShortTermMemory:
    global _short_term_memory_singleton
    if _short_term_memory_singleton is None:
        _short_term_memory_singleton = ShortTermMemory()
    return _short_term_memory_singleton


def get_long_term_memory() -> LongTermMemory:
    global _long_term_memory_singleton
    if _long_term_memory_singleton is None:
        _long_term_memory_singleton = LongTermMemory()
    return _long_term_memory_singleton


def get_workflow_graph(
    request: Request,
    backend_client: Annotated[BackendClient, Depends(get_backend_client)],
    checkpoint_mgr: Annotated[CheckpointManager, Depends(get_checkpoint_manager)],
) -> CompiledStateGraph:
    global _compiled_graph_singleton
    app_graph = getattr(request.app.state, "workflow_graph", None)
    if app_graph is not None:
        return app_graph
    if _compiled_graph_singleton is None:
        _compiled_graph_singleton = compile_agent_workflow(
            checkpointer=checkpoint_mgr.get_default_saver(),
            backend_client=backend_client,
        )
    return _compiled_graph_singleton


async def get_optional_auth_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
) -> str | None:
    """Validate optional Bearer token against AUTH_SECRET if configured, and forward token for Backend calls."""
    if agent_settings.AUTH_SECRET and not agent_settings.is_dev():
        expected = agent_settings.AUTH_SECRET.get_secret_value()
        if not credentials or credentials.credentials != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing Bearer authorization token.",
            )
    return credentials.credentials if credentials else None
