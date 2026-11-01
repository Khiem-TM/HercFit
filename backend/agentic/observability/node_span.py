"""Lớp đệm span cấp node (enabled, name, run_id); callback gốc của graph/model sở hữu span node thật."""
from contextlib import contextmanager
from agentic.observability import annotate

@contextmanager
def span(enabled, name, run_id):
    if run_id:
        annotate(business_run_id=run_id)
    yield
