"""Stable runtime interface; the optional exporter is kept on developer machines."""
from importlib.util import find_spec

from observability.settings import ObservabilitySettings

if ObservabilitySettings().MODE == 'dev' and find_spec('observability._dev') is not None:
    from observability._dev.tracing import (
        Observation, Observer, annotate, current, durable_context, graph_config,
        identify, observed, observer, outcome, span,
    )
else:
    from observability.runtime import (
        Observation, Observer, annotate, current, durable_context, graph_config,
        identify, observed, observer, outcome, span,
    )

__all__ = [
    'Observation', 'Observer', 'annotate', 'current', 'durable_context',
    'graph_config', 'identify', 'observed', 'observer', 'outcome', 'span',
]
