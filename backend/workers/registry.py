"""Job kind -> handler. Each handler finishes its job in its last fenced transaction."""
from domains.analytics.services.jobs import HANDLERS as ANALYTICS
from integrations.google_health.export.dispatch import HANDLERS as EXPORT
from integrations.google_health.export.history import HANDLERS as HISTORY
from integrations.google_health.ingest.jobs import HANDLERS as GOOGLE_HEALTH

HANDLERS = {**GOOGLE_HEALTH, **ANALYTICS, **EXPORT, **HISTORY}


def register(kind: str, handler) -> None:
    HANDLERS[kind] = handler
