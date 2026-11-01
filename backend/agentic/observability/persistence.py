"""Chỉ lưu dòng dõi mờ; GUC cục bộ theo transaction không bao giờ rò sang pool."""
import json
from contextlib import contextmanager
from agentic.observability.tracing import observer, durable_context, Observation, outcome


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
    # Root worker độc lập giữ độ trễ người dùng không phụ thuộc thời gian chờ hàng đợi.
    with manager.request(name, 'worker', state=state):
        yield state
        state.metadata.setdefault('status', 'completed')
