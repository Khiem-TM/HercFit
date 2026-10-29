"""Only opaque lineage is persisted; transaction-local GUCs never leak in pools."""
import json
from contextlib import contextmanager
from observability.tracing import observer, durable_context, Observation, outcome


async def set_psycopg_context(conn, context=None):
    context = durable_context() or context
    if context:
        await conn.execute("SELECT set_config('hercfit.trace_context', %s, true)", (json.dumps(context),))


@contextmanager
def worker_context(name, context=None, **metadata):
    manager = observer()
    state = Observation(manager)
    if isinstance(context, dict):
        state.metadata.update({k: v for k, v in (context.get('metadata') or {}).items() if k in {'thread_id', 'business_run_id', 'action_id'}})
        state.metadata['linked_trace_id'] = context.get('trace_id')
    state.metadata.update(metadata)
    # Independent worker roots keep user latency independent of queue wait.
    with manager.request(name, 'worker', state=state):
        yield state
        state.metadata.setdefault('status', 'completed')
