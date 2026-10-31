"""Request correlation without exporting traces or storing request content.

Keep this interface available in clean checkouts and deployment images. Business
token/cost accounting belongs to agentic.observability.telemetry independently.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache, wraps
from time import monotonic
from uuid import uuid4

from langsmith import tracing_context

from agentic.observability.settings import ObservabilitySettings

current = ContextVar('hercfit_observation', default=None)


@dataclass
class Observation:
    manager: object
    request_id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict = field(default_factory=dict)
    started: float = field(default_factory=monotonic)
    root: object = None
    sampled: bool = False

    def identify(self, user_id, session_id=None, private_values=()):
        pass


class Observer:
    def __init__(self, config=None):
        self.config = config or ObservabilitySettings()
        self.client = None
        self.closed = False

    async def close(self):
        self.closed = True

    def status(self):
        return {
            'enabled': False, 'configured': self.config.configured,
            'propagation_configured': False,
            'capture_mode': self.config.LANGSMITH_CAPTURE_MODE,
            'dropped_operations': 0, 'last_export_error': None,
        }

    @contextmanager
    def request(self, name, service, *, parent=None, state=None):
        state = state or Observation(self)
        mark = current.set(state)
        try:
            # Also suppress SDK auto-tracing when inherited environment flags
            # are enabled. Production never activates the local exporter.
            with tracing_context(enabled=False):
                yield state
        finally:
            current.reset(mark)


@lru_cache
def observer():
    return Observer()


def identify(user_id, session_id=None, private_values=()):
    pass


def annotate(**metadata):
    pass


def outcome(status, **metadata):
    if state := current.get():
        state.metadata['status'] = status


@contextmanager
def span(name, run_type='chain', *, inputs=None, **metadata):
    with tracing_context(enabled=False):
        yield None


def observed(name, run_type='chain', *, capture=(), output=True):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            if current.get() is None:
                with observer().request(name, 'worker' if 'worker' in name else 'agentic'):
                    return await fn(*args, **kwargs)
            with tracing_context(enabled=False):
                return await fn(*args, **kwargs)
        return wrapped
    return decorate


def graph_config(config=None):
    return dict(config or {})


def durable_context():
    return None
