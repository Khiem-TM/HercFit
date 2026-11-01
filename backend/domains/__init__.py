"""Business domains (see docs/module-map.json).

Importing any `domains.<name>.models` package registers every ORM model first
(domains.registry), as the old `models` package did. Schemas stay importable
without SQLAlchemy models, settings or a database.
"""
