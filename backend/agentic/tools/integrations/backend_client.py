from agentic.observability import observed, span
from agentic.observability.propagation import outbound_headers
import asyncio
import hashlib
import logging
import time
import httpx
import jwt
from core import service_auth
from pydantic import TypeAdapter
from agentic.tools.registry import REGISTRY
from domains.identity.schemas.user import UserRead

class BackendError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(str(detail))

logger = logging.getLogger(__name__)
DELEGATION_PATH = '/api/v2/auth/delegations'
DELEGATION_SKEW_SECONDS = 60


class BackendClient:
    def __init__(self, base_url, timeout=15, transport=None, service_secret=None):
        self.http = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)
        # Khi có service secret, agent đọc bằng token uỷ quyền do backend cấp, nên
        # consent được thực thi từ chính token thay vì một header tự khai báo.
        self.service_secret = service_secret
        self._delegations = {}

    async def delegated_token(self, token):
        """Token uỷ quyền đã cache cho token người dùng này, hoặc None (dự phòng: token người dùng + header)."""
        if not self.service_secret:
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        cached = self._delegations.get(key)
        now = time.time()
        if cached and cached[1] - DELEGATION_SKEW_SECONDS > now:
            return cached[0]
        try:
            subject = str(jwt.decode(token, options={'verify_signature': False}).get('sub') or '')
        except jwt.PyJWTError:
            return None
        proof = service_auth.sign(self.service_secret, 'POST', DELEGATION_PATH, subject, b'')
        try:
            response = await self.http.post(DELEGATION_PATH, headers={
                'Authorization': 'Bearer ' + token, service_auth.HEADER: proof})
        except httpx.TransportError:
            return None
        if response.status_code != 200:
            logger.warning('backend_delegation_failed status=%s', response.status_code)
            return None
        data = response.json()
        try:
            expires = jwt.decode(data['access_token'], options={'verify_signature': False})['exp']
        except (KeyError, jwt.PyJWTError):
            return None
        if len(self._delegations) > 1000:
            self._delegations = {k: v for k, v in self._delegations.items() if v[1] > now}
        self._delegations[key] = (data['access_token'], float(expires))
        return data['access_token']

    async def close(self):
        await self.http.aclose()

    @observed('backend.request', capture=('method', 'path', 'params', 'body'), output=False)
    async def request(self, method, path, token, *, params=None, body=None, key=None):
        # Backend áp consent của người dùng lên các lần đọc của trợ lý: ưu tiên từ token
        # uỷ quyền; header tự khai báo chỉ còn cho giai đoạn chuyển tiếp.
        delegated = await self.delegated_token(token)
        headers = {'Authorization': 'Bearer ' + (delegated or token), 'X-HercFit-Client': 'agent'}
        if key:
            headers['Idempotency-Key'] = key # Trống trùng lặp
        attempts = 3 if method == 'GET' or key else 1
        for attempt in range(attempts):
            try:
                with span('backend.http_attempt', 'tool', attempt=attempt+1, method=method) as run:
                    response = await self.http.request(method, path, headers={**headers, **outbound_headers(method, path)}, params=params, json=body)
                    if run:
                        run.add_metadata({'http_status': response.status_code, 'attempt': attempt+1})
                        if response.is_error:
                            run.error = f'HTTP{response.status_code}'
                if response.status_code >= 500 and attempt + 1 < attempts:
                    await asyncio.sleep(.1 * 2**attempt)
                    continue
                if response.is_error:
                    # Giữ lỗi theo trường có cấu trúc, không bao giờ giữ header/token của request.
                    try:
                        detail = response.json().get('detail', 'Backend request failed')
                    except ValueError:
                        detail = 'Backend request failed'
                    raise BackendError(response.status_code, detail)
                return response.json() if response.content else None
            except httpx.TransportError:
                if attempt + 1 == attempts:
                    raise BackendError(503, 'Backend unavailable; write outcome may be unknown') from None
                await asyncio.sleep(.1 * 2**attempt)

    async def identity(self, token):
        data = await self.request('GET', '/api/profile', token)
        return UserRead.model_validate(data)

    @observed('backend.tool', 'tool', capture=('name', 'args'))
    async def call(self, name, args, token, key=None):
        spec = REGISTRY[name]
        if spec.write and not key:
            raise RuntimeError('A write requires an approved action idempotency key')
        args = spec.normalize(args)
        path, params, body = spec.request_parts(args)
        if name == 'merge_personal_info':
            body = body['personal_info']
        data = await self.request(spec.method, path, token, params=params, body=body, key=key)
        if spec.output is None:
            return None
        adapter = TypeAdapter(spec.output)
        return adapter.dump_python(adapter.validate_python(data), mode='json')
