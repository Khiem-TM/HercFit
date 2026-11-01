"""python -m workers run [--queues ingest,export,maint] [--concurrency 4] [--no-scheduler]
python -m workers drain   # chạy các job sẵn sàng một lần rồi thoát (vận hành, test)
python -m workers tick    # một tick của scheduler
python -m workers metrics # số liệu hàng đợi, độ trễ, xuất và webhook dạng JSON
"""
import argparse
import asyncio
import logging
import signal

import httpx

from core.database import close_crud_db_pool


async def main() -> None:
    import integrations  # noqa: F401  (đăng ký model ORM và port nhà cung cấp)
    from workers import runner, scheduler
    from workers.registry import HANDLERS

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("run", "drain", "tick", "metrics"))
    parser.add_argument("--queues", default="ingest,export,maint")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--no-scheduler", action="store_true")
    args = parser.parse_args()
    queues = tuple(name for name in args.queues.split(",") if name)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        if args.command == "tick":
            print(await scheduler.tick())
        elif args.command == "metrics":
            import json

            from workers.metrics import collect
            print(json.dumps(await collect(), indent=2, default=str))
        elif args.command == "drain":
            async with httpx.AsyncClient() as http:
                print(await runner.drain(queues, HANDLERS, http, owner=runner.owner_name(0), limit=10_000))
        else:
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop.set)
            tasks = [runner.run(queues, args.concurrency, HANDLERS, stop)]
            if not args.no_scheduler:
                tasks.append(scheduler.loop(stop))
            await asyncio.gather(*tasks)
    finally:
        await close_crud_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
