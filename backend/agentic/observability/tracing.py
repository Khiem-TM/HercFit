"""Interface runtime ổn định; chọn exporter Langfuse khi được bật, ngược lại dùng bản no-op."""

from importlib.util import find_spec

from agentic.observability.settings import ObservabilitySettings

if ObservabilitySettings().enabled and find_spec("langfuse") is not None:
    from agentic.observability.langfuse_adapter import (
        Observation,
        Observer,
        annotate,
        current,
        durable_context,
        graph_config,
        identify,
        observed,
        observer,
        outcome,
        span,
    )
else:
    from agentic.observability.runtime import (
        Observation,
        Observer,
        annotate,
        current,
        durable_context,
        graph_config,
        identify,
        observed,
        observer,
        outcome,
        span,
    )

__all__ = [
    "Observation",
    "Observer",
    "annotate",
    "current",
    "durable_context",
    "graph_config",
    "identify",
    "observed",
    "observer",
    "outcome",
    "span",
]
