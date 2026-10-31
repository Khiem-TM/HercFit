"""Node-level span shim (enabled, name, run_id); native graph/model callbacks own the real node spans."""
from contextlib import contextmanager
from agentic.observability import annotate

@contextmanager
def span(enabled, name, run_id):
    if run_id:
        annotate(business_run_id=run_id)
    yield
