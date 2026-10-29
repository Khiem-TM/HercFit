"""Pure ASGI middleware keeps roots/context alive for the entire SSE response."""
import asyncio
import logging
from time import monotonic
from agentic.observability.tracing import observer, Observation
from agentic.observability.propagation import trusted_parent, TRACE_HEADERS

log = logging.getLogger('hercfit.requests')


class ObservabilityMiddleware:
    def __init__(self, app, service, manager=None, accept_parent=False):
        self.app, self.service, self.manager = app, service, manager
        self.accept_parent = accept_parent

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'].startswith(('/health', '/docs', '/openapi')):
            return await self.app(scope, receive, send)
        manager = self.manager or observer()
        headers = {k.decode().lower(): v.decode() for k, v in scope.get('headers', [])}
        parent = trusted_parent(manager.config, scope['method'], scope['path'], headers) if self.accept_parent else None
        # Strip all caller-controlled trace headers before downstream handlers.
        scope = {**scope, 'headers': [(k, v) for k, v in scope.get('headers', []) if k.decode().lower() not in TRACE_HEADERS]}
        state = Observation(manager)
        code = 500
        disconnected = False
        async def receive_request():
            nonlocal disconnected
            message = await receive()
            if message['type'] == 'http.disconnect':
                disconnected = True
            return message
        async def send_response(message):
            nonlocal code
            if message['type'] == 'http.response.start':
                code = message['status']
                message = {**message, 'headers': [*message.get('headers', []),
                    (b'x-request-id', state.request_id.encode()), (b'x-trace-id', state.trace_id.encode())]}
            await send(message)
        with manager.request('http.' + self.service, self.service, parent=parent, state=state):
            try:
                await self.app(scope, receive_request, send_response)
            except asyncio.CancelledError:
                state.metadata['status'] = 'cancelled'
                raise
            finally:
                route = scope.get('route')
                state.metadata.update(method=scope['method'], route=getattr(route, 'path', 'unmatched'), http_status=code)
                state.metadata.setdefault('status', 'cancelled' if disconnected else 'failed' if code >= 400 else 'completed')
                if code >= 400:
                    state.metadata.setdefault('error_code', f'HTTP{code}')
                log.info('request_finished request_id=%s trace_id=%s service=%s status=%s http_status=%d duration_ms=%.3f',
                         state.request_id, state.trace_id, self.service, state.metadata['status'], code, (monotonic()-state.started)*1000)
