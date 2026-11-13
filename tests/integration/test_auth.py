"""Mặc định an toàn của xác thực (L5.1): GET không làm mới phiên, POST /auth/refresh bắt buộc Origin hợp lệ, agent
phải dùng token uỷ quyền khi không cấu hình gì."""
from core.security import REFRESH_TOKEN_COOKIE_NAME
from core.settings import Settings, settings

LOGIN, REFRESH = "/api/auth/login", "/api/auth/refresh"


async def test_get_login_never_renews_a_session(client):
    client.cookies.set(REFRESH_TOKEN_COOKIE_NAME, "any-refresh-token")
    for params in ({}, {"mode": "refresh"}):
        response = await client.get(LOGIN, params=params)
        assert response.status_code == 400
        assert "set-cookie" not in response.headers


async def test_refresh_requires_an_allowed_origin(client):
    assert (await client.post(REFRESH)).status_code == 403
    assert (await client.post(REFRESH, headers={"Origin": "https://evil.example"})).status_code == 403
    # Origin hợp lệ qua được cổng CSRF; không có cookie refresh thì là lỗi xác thực, không phải 403.
    allowed = await client.post(REFRESH, headers={"Origin": settings.FRONTEND_URL.rstrip("/")})
    assert allowed.status_code == 401


def test_agent_delegation_is_required_by_default():
    assert Settings.model_fields["AGENT_DELEGATION_REQUIRED"].default is True
