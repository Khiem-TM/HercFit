"""POST /internal/notifications/compose: backend gửi feature và nhãn đã tính, nhận lại lời thông báo do LLM viết.

Chỉ backend gọi được: chữ ký HMAC (core/service_auth) trên method, đường dẫn, người dùng và thân request, bằng
AGENT_SERVICE_SECRET dùng chung. Không có khoá thì endpoint đóng (503); sai chữ ký thì 401; model không viết được
lời hợp lệ thì 422 để backend dùng câu chữ do code viết.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from core import service_auth
from agentic.services import notification_composer

router = APIRouter(prefix='/internal/notifications', include_in_schema=False)


@router.post('/compose')
async def compose(request: Request):
    settings = request.app.state.settings
    secret = settings.AGENT_SERVICE_SECRET.get_secret_value() if getattr(settings, 'AGENT_SERVICE_SECRET', None) else ''
    if not secret:
        raise HTTPException(503, 'Notification composer is not configured')
    body = await request.body()
    user = request.headers.get('X-HercFit-User', '')
    if not user or not service_auth.verify([secret], request.headers.get(service_auth.HEADER), 'POST',
                                            request.url.path, user, body):
        raise HTTPException(401, 'Invalid service signature')
    try:
        payload = notification_composer.ComposeRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(422, 'Invalid compose request') from exc
    try:
        return await notification_composer.compose(request.app.state.models, payload)
    except notification_composer.ComposeError as exc:
        raise HTTPException(422, 'Could not compose a grounded notification') from exc
