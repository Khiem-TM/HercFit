"""Transactional PostgreSQL migrations using Alembic with AsyncEngine."""
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from core.database import get_sqlalchemy_url
from models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def migration_url() -> str:
    """Return migration database URL from alembic config, environment, or application settings."""
    return (
        config.get_main_option("sqlalchemy.url")
        or os.getenv("MIGRATION_DATABASE_URL")
        or str(get_sqlalchemy_url())
    )


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in (None, "public")
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode without a live connection."""
    url = migration_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Configure migration context and execute migrations inside a transaction."""
    # Auto-align existing database if stamped with obsolete multi-revision IDs
    if connection.dialect.has_table(connection, "alembic_version"):
        connection.execute(
            text(
                "UPDATE alembic_version SET version_num = '0001_initial_schema' "
                "WHERE version_num IN ('0002_current_baseline', '0003_plans_and_journals')"
            )
        )

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an AsyncEngine and run migrations in online mode."""
    connectable = create_async_engine(migration_url(), poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with a live connection."""
    existing = config.attributes.get("connection")
    if existing is not None:
        do_run_migrations(existing)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
