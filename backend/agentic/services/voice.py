"""Token phòng LiveKit cho lớp hội thoại giọng nói: mỗi phiên voice là một phòng riêng của người dùng.

Voice chỉ là lớp vào/ra. Worker (backend/voice/worker.py) chuyển giọng nói thành văn bản và đọc câu trả lời;
lượt chat vẫn do trình duyệt gửi qua /chat/stream, nên worker không bao giờ cần JWT của người dùng.
"""

from time import time
from uuid import uuid4

import jwt

# Phải khớp AGENT_NAME trong backend/voice/worker.py: LiveKit gọi đúng worker này vào phòng.
AGENT_NAME = "hercfit-voice"
# Token chỉ dùng để vào phòng; phiên đang mở không bị ngắt khi token hết hạn.
TOKEN_TTL_SECONDS = 600


def room_token(settings, user_id: str) -> dict | None:
    """`{url, token}` để trình duyệt vào phòng, hoặc None khi LiveKit chưa được cấu hình."""
    if not (settings.LIVEKIT_URL and settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET):
        return None
    now = int(time())
    claims = {
        "iss": settings.LIVEKIT_API_KEY,
        "sub": user_id,
        "nbf": now,
        "exp": now + TOKEN_TTL_SECONDS,
        "video": {
            "room": f"voice-{user_id}-{uuid4().hex[:8]}",
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        },
        "roomConfig": {"agents": [{"agentName": AGENT_NAME}]},
    }
    token = jwt.encode(claims, settings.LIVEKIT_API_SECRET.get_secret_value(), algorithm="HS256")
    return {"url": settings.LIVEKIT_URL, "token": token}
