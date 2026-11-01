"""External providers. Only this package talks to third-party health APIs.

Integration models (health_connections, ...) belong to the ORM registry; load it
first so importing one of them directly cannot start a circular import. Each
provider then registers its implementation of the domain ports.
"""
import domains.registry  # noqa: F401
import integrations.google_health.directory  # noqa: E402,F401
