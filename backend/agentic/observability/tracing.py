"""Stable runtime interface; the optional exporter is kept on developer machines."""
from importlib.util import find_spec

from agentic.observability.settings import ObservabilitySettings

if ObservabilitySettings().MODE == 'dev' and find_spec('agentic.observability._dev') is not None:
    from agentic.observability._dev.tracing import (
        Observation, Observer, annotate, current, durable_context, graph_config,
        identify, observed, observer, outcome, span,
    )
else:
    from agentic.observability.runtime import (
        Observation, Observer, annotate, current, durable_context, graph_config,
        identify, observed, observer, outcome, span,
    )

__all__ = [
    'Observation', 'Observer', 'annotate', 'current', 'durable_context',
    'graph_config', 'identify', 'observed', 'observer', 'outcome', 'span',
]
