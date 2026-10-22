"""Driver creation is lazy so KG_MODE=off does not need the Neo4j package."""


def value(settings, name, default=None):
    item = getattr(settings, name, default)
    return item.get_secret_value() if hasattr(item, 'get_secret_value') else item


def create_driver(settings):
    from neo4j import AsyncGraphDatabase

    return AsyncGraphDatabase.driver(
        value(settings, 'NEO4J_URI', 'bolt://localhost:7687'),
        auth=(value(settings, 'NEO4J_USER', 'neo4j'), value(settings, 'NEO4J_PASSWORD')),
        connection_timeout=2.0,
        connection_acquisition_timeout=2.0,
        max_transaction_retry_time=0.0,
        disable_auto_commit_retries=True,
        max_connection_pool_size=20,
    )
