"""python -m integrations.google_health [--user UUID] [--days N] [--publish-kg]

Đồng bộ ngay một người dùng (hoặc mọi kết nối đang hoạt động). --publish-kg phát lại dữ kiện
sức khoẻ lên knowledge graph (sau khi dựng lại graph từ đầu, vì kg_enqueue_snapshot không quét
health_points).
"""
import argparse
import asyncio
import json
from datetime import date, timedelta
from uuid import UUID

import domains.registry  # noqa: F401
from core.database import close_crud_db_pool, get_db_session
from domains.health_records import views
from integrations.google_health.sync import run, sync_all


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", type=UUID, help="Chỉ đồng bộ người dùng này")
    parser.add_argument("--days", type=int, help="Số ngày gần nhất cần đọc lại (mặc định 7, lần đầu 90)")
    parser.add_argument("--publish-kg", action="store_true", help="Chỉ phát lại dữ kiện sức khoẻ lên graph")
    args = parser.parse_args()
    try:
        if args.publish_kg:
            today = date.today()
            async with get_db_session() as session:
                count = await views.publish_kg(session, args.user, today - timedelta(days=args.days or 90), today)
            print(f"Published {count} health facts")
        elif args.user:
            print(json.dumps(await run(args.user, days=args.days), ensure_ascii=False, indent=2, default=str))
        else:
            print(f"Synchronized {await sync_all(days=args.days)} connection(s)")
    finally:
        await close_crud_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
