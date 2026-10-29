"""Operational maintenance for the agent database.

    python -m agentic.scripts.maintenance prune-checkpoints [--days 30] [--dry-run]
    python -m agentic.scripts.maintenance prune-usage [--days 120]

Each chat turn runs on its own LangGraph thread, so checkpoints grow with every
turn. Superseded threads older than the retention window are deleted; a
session's current thread (needed for history and pending confirmations) and
threads still awaiting reconciliation are always kept.
"""
import argparse
import asyncio

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agentic.core.app.config import agent_settings
from agentic.services.memory.store import Store


async def prune_checkpoints(store, saver, days, dry_run=False, batch=500):
    removed = 0
    while True:
        rows = await store.stale_threads(days, batch)
        if not rows or dry_run:
            return removed + (len(rows) if dry_run else 0)
        for row in rows:
            await saver.adelete_thread(row['thread_id'])
            await store.forget_thread(row['thread_id'])
            removed += 1


async def prune_usage(pool, days):
    async with pool.connection() as conn:
        result = await conn.execute("DELETE FROM agent_usage_daily WHERE day < current_date - make_interval(days => %s)", (days,))
        return result.rowcount


async def main():
    parser = argparse.ArgumentParser(description="Agent database maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    prune = sub.add_parser("prune-checkpoints")
    prune.add_argument("--days", type=int, default=agent_settings.CHECKPOINT_RETENTION_DAYS)
    prune.add_argument("--dry-run", action="store_true")
    usage = sub.add_parser("prune-usage")
    usage.add_argument("--days", type=int, default=120)
    args = parser.parse_args()
    async with AsyncConnectionPool(agent_settings.AGENT_DATABASE_URL.get_secret_value(), min_size=1, max_size=4,
                                   open=False, kwargs={"autocommit": True, "row_factory": dict_row}) as pool:
        await pool.open(wait=True)
        if args.command == "prune-checkpoints":
            count = await prune_checkpoints(Store(pool), AsyncPostgresSaver(pool), args.days, args.dry_run)
            print(("Would delete" if args.dry_run else "Deleted"), count, "superseded threads")
        else:
            print("Deleted", await prune_usage(pool, args.days), "daily usage rows")


if __name__ == "__main__":
    asyncio.run(main())
