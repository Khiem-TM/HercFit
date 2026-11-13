"""Quyền của chủ thể dữ liệu: xuất mọi thứ người dùng sở hữu, hoặc xoá tài khoản.

Việc xoá sẽ xoá dòng users; khoá ngoại xoá dây chuyền tới mọi bảng sở hữu và các
trigger ghi nhận knowledge graph phát sự kiện xoá, nên phép chiếu Neo4j được
worker dọn. Quyền Google Health được thu hồi tại Google trước. Ảnh gắn với bản ghi của người dùng được xếp hàng
để xoá trên Cloudinary trước. Dữ liệu hội thoại nằm trong service agent: backend gọi endpoint nội bộ của agent
(purge_agent_conversations) trước khi xoá bất cứ thứ gì, và dừng nếu agent không xoá được.
"""
import logging
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from core import service_auth
from core.settings import settings

logger = logging.getLogger(__name__)
AGENT_CONVERSATIONS_PATH = "/internal/users/{user_id}/conversations"
# Xoá hội thoại có thể duyệt nhiều phiên: thời gian chờ rộng hơn lời gọi viết thông báo.
AGENT_PURGE_TIMEOUT_SECONDS = 30
ERASE_UNAVAILABLE = "Chưa xoá được lịch sử trò chuyện nên tài khoản chưa bị xoá. Vui lòng thử lại sau."

EXPORT_FORMAT_VERSION = 1
# Chỉ dùng SQL hằng; :uid là id của người dùng đã xác thực.
EXPORT_QUERIES: tuple[tuple[str, str], ...] = (
    ("profile", "SELECT id, email, fullname, nick_name, avatar_url, email_verified, last_login_at, is_onboarding, "
                "age, sex, personal_info, created_at, updated_at FROM users WHERE id = :uid"),
    ("linked_accounts", "SELECT provider, provider_user_id, created_at FROM oauth_accounts WHERE user_id = :uid"),
    ("sign_in_sessions", "SELECT created_at, expires_at, revoked_at FROM auth_sessions WHERE user_id = :uid ORDER BY created_at"),
    ("body_metrics", "SELECT * FROM body_metrics WHERE user_id = :uid ORDER BY recorded_at"),
    ("goals", "SELECT * FROM goals WHERE user_id = :uid ORDER BY created_at"),
    ("meals", "SELECT * FROM meals WHERE user_id = :uid ORDER BY consumed_at"),
    ("meal_items", "SELECT i.* FROM meal_items i JOIN meals m ON m.id = i.meal_id WHERE m.user_id = :uid "
                   "ORDER BY m.consumed_at, i.position"),
    ("trainings", "SELECT * FROM trainings WHERE user_id = :uid ORDER BY started_at"),
    ("training_items", "SELECT i.* FROM training_items i JOIN trainings t ON t.id = i.training_id "
                       "WHERE t.user_id = :uid ORDER BY t.started_at, i.position"),
    ("plans", "SELECT * FROM plans WHERE user_id = :uid ORDER BY created_at"),
    ("training_plans", "SELECT * FROM training_plans WHERE user_id = :uid ORDER BY created_at"),
    ("training_plan_entries", "SELECT e.* FROM training_plan_entries e JOIN training_plans p ON p.id = e.training_plan_id "
                              "WHERE p.user_id = :uid ORDER BY e.scheduled_date, e.position"),
    ("training_plan_items", "SELECT i.* FROM training_plan_items i JOIN training_plan_entries e ON e.id = i.entry_id "
                            "JOIN training_plans p ON p.id = e.training_plan_id WHERE p.user_id = :uid "
                            "ORDER BY e.scheduled_date, i.position"),
    ("custom_foods", "SELECT * FROM foods WHERE owner_user_id = :uid ORDER BY created_at"),
    ("custom_exercises", "SELECT * FROM exercises WHERE owner_user_id = :uid ORDER BY created_at"),
    # Thông tin xác thực nhà cung cấp không bao giờ được xuất; chỉ metadata của quyền đã cấp.
    ("health_connections", "SELECT provider, account_email, granted_scopes, status, share_with_assistant, consented_at, "
                           "timezone, provider_profile, last_sync_at, last_success_at, created_at "
                           "FROM health_connections WHERE user_id = :uid"),
    ("health_points", "SELECT data_type, kind, start_at, end_at, local_date, value, written_by_hercfit "
                      "FROM health_points WHERE user_id = :uid ORDER BY data_type, local_date, start_at"),
)
IMAGE_TABLES = (("meals", "user_id"), ("trainings", "user_id"), ("foods", "owner_user_id"), ("exercises", "owner_user_id"))


async def export_user_data(session, user_id) -> dict:
    data: dict = {"format_version": EXPORT_FORMAT_VERSION,
                  "exported_at": datetime.now(timezone.utc).isoformat(), "service": "hercfit-backend"}
    for name, sql in EXPORT_QUERIES:
        rows = (await session.execute(text(sql), {"uid": user_id})).mappings().all()
        data[name] = jsonable_encoder([dict(row) for row in rows])
    data["profile"] = data["profile"][0] if data["profile"] else None
    data["notes"] = ("Hội thoại với trợ lý được lưu ở dịch vụ agent; xuất hoặc xoá qua /api/v1/chat. "
                     "Bản ghi nhật ký là snapshot bất biến; các bản đã thay thế có is_active=false.")
    return data


async def purge_agent_conversations(user_id) -> dict:
    """Xoá mọi cuộc trò chuyện của người dùng ở service agent (endpoint nội bộ ký HMAC). Không xoá được thì 503 để bên
    gọi chưa xoá gì ở backend: không bao giờ còn hội thoại mồ côi sau khi tài khoản đã mất."""
    secret = settings.AGENT_SERVICE_SECRET.get_secret_value() if settings.AGENT_SERVICE_SECRET else ""
    if not settings.AGENTIC_INTERNAL_URL or not secret:
        raise HTTPException(503, ERASE_UNAVAILABLE)
    path = AGENT_CONVERSATIONS_PATH.format(user_id=user_id)
    headers = {service_auth.HEADER: service_auth.sign(secret, "DELETE", path, str(user_id))}
    try:
        async with httpx.AsyncClient(base_url=settings.AGENTIC_INTERNAL_URL,
                                     timeout=AGENT_PURGE_TIMEOUT_SECONDS) as client:
            response = await client.delete(path, headers=headers)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("agent_conversation_purge_failed error=%s", type(exc).__name__)
        raise HTTPException(503, ERASE_UNAVAILABLE) from None


async def erase_user(session, user_id) -> dict:
    """Xoá cứng tài khoản trong transaction của bên gọi; trả về số đếm cho biên nhận."""
    from domains.health_records import ports

    # Thu hồi quyền tại nhà cung cấp trước (cố gắng hết mức); bản thân các dòng sẽ bị xoá dây chuyền.
    await ports.before_account_erasure(session, user_id)
    images = 0
    if settings.CLOUDINARY_CLOUD_NAME:
        for table, owner in IMAGE_TABLES:
            result = await session.execute(text(
                f"INSERT INTO image_cleanup (public_id, cloud_name) SELECT image_public_id, :cloud FROM {table} "
                f"WHERE {owner} = :uid AND image_public_id IS NOT NULL ON CONFLICT (public_id) DO NOTHING"
            ), {"uid": user_id, "cloud": settings.CLOUDINARY_CLOUD_NAME})
            images += result.rowcount or 0
    counts = {}
    for name in ("meals", "trainings", "body_metrics", "goals", "health_points", "google_pushes"):
        counts[name] = (await session.execute(text(f"SELECT count(*) FROM {name} WHERE user_id = :uid"),
                                              {"uid": user_id})).scalar_one()
    deleted = (await session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})).rowcount
    return {"erased": bool(deleted), "records": counts, "images_queued_for_removal": images}
