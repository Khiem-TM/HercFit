"""Bound multipart bodies before the parser can spool unbounded uploads to disk."""
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from core.settings import settings


class ImageUploadLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'PUT' or not scope['path'].startswith('/api/media/'):
            return await self.app(scope, receive, send)
        limit = settings.IMAGE_MAX_BYTES + 64 * 1024  # multipart fields/boundaries
        headers = dict(scope.get('headers', []))
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            length = 0
        if length > limit:
            return await JSONResponse({'detail': 'Ảnh vượt quá dung lượng cho phép'}, status_code=413)(scope, receive, send)
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            total += len(message.get('body', b''))
            if total > limit:
                raise HTTPException(413, 'Ảnh vượt quá dung lượng cho phép')
            return message

        await self.app(scope, limited_receive, send)
