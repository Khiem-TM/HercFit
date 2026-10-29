from agentic.observability import observed, span
from agentic.observability.propagation import outbound_headers
import asyncio
import httpx
from pydantic import TypeAdapter
from agentic.tools.registry import REGISTRY
from schemas.user import UserRead

class BackendError(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(str(detail))

class BackendClient:
    def __init__(self, base_url, timeout=15, transport=None):
        self.http = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def close(self):
        await self.http.aclose()

    @observed('backend.request', capture=('method', 'path', 'params', 'body'), output=False)
    async def request(self, method, path, token, *, params=None, body=None, key=None):
        headers = {'Authorization': 'Bearer ' + token}
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
                    # Preserve structured field errors, never request headers/tokens.
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
