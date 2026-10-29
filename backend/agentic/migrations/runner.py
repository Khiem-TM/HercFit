"""One ordered migration path shared by deployment and development startup."""
from pathlib import Path

MIGRATION_DIRECTORY = Path(__file__).parent
EXPECTED_SCHEMA_VERSION = 8


async def migrate_pool(pool, saver):
    async with pool.connection() as conn:
        # Saver.setup uses CREATE INDEX CONCURRENTLY outside SQL transactions.
        await conn.execute('SELECT pg_advisory_lock(19482173)')
        try:
            await conn.execute('CREATE TABLE IF NOT EXISTS agent_schema_version (version integer PRIMARY KEY)')
            rows = await (await conn.execute('SELECT version FROM agent_schema_version')).fetchall()
            applied = {row['version'] for row in rows}
            for path in sorted(MIGRATION_DIRECTORY.glob('[0-9]*_*.sql')):
                version = int(path.name.split('_', 1)[0])
                if version not in applied:
                    async with conn.transaction():
                        await conn.execute(path.read_text())
                        await conn.execute('INSERT INTO agent_schema_version VALUES (%s) ON CONFLICT DO NOTHING', (version,))
            await saver.setup()
        finally:
            await conn.execute('SELECT pg_advisory_unlock(19482173)')
