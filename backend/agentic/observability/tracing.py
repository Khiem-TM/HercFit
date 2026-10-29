"""Compatibility for old call sites; native graph/model callbacks own node spans."""
from contextlib import contextmanager
from observability import annotate

@contextmanager
def span(enabled, name, run_id):
    if run_id:
        annotate(business_run_id=run_id)
    yield
