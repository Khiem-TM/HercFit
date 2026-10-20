"""Custom exceptions for the HercFit Agentic Service."""

from typing import Any


class AgenticBaseError(Exception):
    """Base exception for all errors inside the Agentic service."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "AGENTIC_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class ConfigurationError(AgenticBaseError):
    """Raised when LLM or Agent configuration is missing or invalid."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="CONFIGURATION_ERROR",
            status_code=500,
            details=details,
        )


class LLMProviderError(AgenticBaseError):
    """Raised when an LLM provider fails to initialize or respond."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="LLM_PROVIDER_ERROR",
            status_code=502,
            details=details,
        )


class RoutingError(AgenticBaseError):
    """Raised when the Router/Supervisor agent fails to determine a valid route."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="ROUTING_ERROR",
            status_code=422,
            details=details,
        )


class AgentExecutionError(AgenticBaseError):
    """Raised when a specialized agent encounters an unrecoverable runtime failure."""

    def __init__(
        self,
        message: str,
        *,
        agent_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = dict(details or {})
        if agent_name:
            merged_details["agent_name"] = agent_name
        super().__init__(
            message,
            code="AGENT_EXECUTION_ERROR",
            status_code=500,
            details=merged_details,
        )


class ToolCallError(AgenticBaseError):
    """Raised when a tool invocation fails validation or execution."""

    def __init__(
        self,
        message: str,
        *,
        tool_name: str,
        payload: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = dict(details or {})
        merged_details["tool_name"] = tool_name
        if payload is not None:
            merged_details["payload"] = payload
        super().__init__(
            message,
            code="TOOL_CALL_ERROR",
            status_code=500,
            details=merged_details,
        )
        self.tool_name = tool_name
        self.payload = payload


class BackendAPIError(AgenticBaseError):
    """Raised when an HTTP call to the internal HercFit CRUD Backend fails."""

    def __init__(
        self,
        message: str,
        *,
        endpoint: str,
        status_code: int = 502,
        response_body: Any = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged_details = dict(details or {})
        merged_details.update(
            {
                "endpoint": endpoint,
                "upstream_status": status_code,
                "response_body": response_body,
            }
        )
        super().__init__(
            message,
            code="BACKEND_API_ERROR",
            status_code=status_code if 400 <= status_code < 600 else 502,
            details=merged_details,
        )
        self.endpoint = endpoint
        self.response_body = response_body


class MemoryStoreError(AgenticBaseError):
    """Raised when short-term or long-term memory persistence fails."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="MEMORY_STORE_ERROR",
            status_code=500,
            details=details,
        )

