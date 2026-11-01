"""python -m services.google_health [--connection-id UUID]: sync due connections once."""
import argparse
import asyncio
import json
from uuid import UUID

from core.database import close_crud_db_pool
from integrations.google_health.scheduler import sync_due
from integrations.google_health.sync import sync_connection


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection-id", type=UUID, help="Sync this connection now (manual trigger)")
    args = parser.parse_args()
    try:
        if args.connection_id:
            print(json.dumps(await sync_connection(args.connection_id, trigger="MANUAL"), ensure_ascii=False, indent=2))
        else:
            print(f"Synchronized {await sync_due()} connection(s)")
    finally:
        await close_crud_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
