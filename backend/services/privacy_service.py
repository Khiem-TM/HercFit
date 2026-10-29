"""Data-subject rights: export everything a user owns, or erase the account.

Erasure deletes the users row; foreign keys cascade to every owned table and the
knowledge-graph capture triggers emit delete events, so the Neo4j projection is
cleaned by the worker. Images attached to the user's records are queued for
Cloudinary removal first. Conversation data lives in the agent service, which
exposes its own purge endpoint (DELETE /api/v1/chat/me).
"""
from datetime import datetime, timezone

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from core.settings import settings

EXPORT_FORMAT_VERSION = 1
# Constant SQL only; :uid is the authenticated user's id.
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
    ("meal_plans", "SELECT * FROM meal_plans WHERE user_id = :uid ORDER BY created_at"),
    ("meal_plan_entries", "SELECT e.* FROM meal_plan_entries e JOIN meal_plans p ON p.id = e.meal_plan_id "
                          "WHERE p.user_id = :uid ORDER BY e.scheduled_date, e.position"),
    ("meal_plan_items", "SELECT i.* FROM meal_plan_items i JOIN meal_plan_entries e ON e.id = i.entry_id "
                        "JOIN meal_plans p ON p.id = e.meal_plan_id WHERE p.user_id = :uid ORDER BY e.scheduled_date, i.position"),
    ("training_plans", "SELECT * FROM training_plans WHERE user_id = :uid ORDER BY created_at"),
    ("training_plan_entries", "SELECT e.* FROM training_plan_entries e JOIN training_plans p ON p.id = e.training_plan_id "
                              "WHERE p.user_id = :uid ORDER BY e.scheduled_date, e.position"),
    ("training_plan_items", "SELECT i.* FROM training_plan_items i JOIN training_plan_entries e ON e.id = i.entry_id "
                            "JOIN training_plans p ON p.id = e.training_plan_id WHERE p.user_id = :uid "
                            "ORDER BY e.scheduled_date, i.position"),
    ("custom_foods", "SELECT * FROM foods WHERE owner_user_id = :uid ORDER BY created_at"),
    ("custom_exercises", "SELECT * FROM exercises WHERE owner_user_id = :uid ORDER BY created_at"),
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


async def erase_user(session, user_id) -> dict:
    """Hard-delete the account in the caller's transaction; returns counts for the receipt."""
    images = 0
    if settings.CLOUDINARY_CLOUD_NAME:
        for table, owner in IMAGE_TABLES:
            result = await session.execute(text(
                f"INSERT INTO image_cleanup (public_id, cloud_name) SELECT image_public_id, :cloud FROM {table} "
                f"WHERE {owner} = :uid AND image_public_id IS NOT NULL ON CONFLICT (public_id) DO NOTHING"
            ), {"uid": user_id, "cloud": settings.CLOUDINARY_CLOUD_NAME})
            images += result.rowcount or 0
    counts = {}
    for name in ("meals", "trainings", "body_metrics", "goals"):
        counts[name] = (await session.execute(text(f"SELECT count(*) FROM {name} WHERE user_id = :uid"),
                                              {"uid": user_id})).scalar_one()
    deleted = (await session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})).rowcount
    return {"erased": bool(deleted), "records": counts, "images_queued_for_removal": images}
