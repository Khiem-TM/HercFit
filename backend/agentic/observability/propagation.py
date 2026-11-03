"""Chỉ header service-tới-service có chữ ký mới được tiếp tục một trace."""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import unquote
from agentic.observability.tracing import current, durable_context

TRACE_HEADERS = {'traceparent', 'tracestate', 'baggage', 'x-hercfit-trace-time', 'x-hercfit-trace-signature'}
# W3C traceparent: version-trace_id(32 hex)-parent_id(16 hex)-flags.
TRACEPARENT = re.compile(r'^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$')


def _signature(secret, method, path, timestamp, headers):
    message = '\n'.join((method.upper(), path.split('?')[0], timestamp, headers.get('traceparent', ''), headers.get('baggage', '')))
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def outbound_headers(method, path):
    state = current.get()
    if not state or not state.manager.config.LANGFUSE_PROPAGATION_SECRET:
        return {}
    context = durable_context()
    if not context:
        return {}
    headers = dict(context['headers'])
    stamp = str(int(time.time()))
    headers['x-hercfit-trace-time'] = stamp
    headers['x-hercfit-trace-signature'] = _signature(state.manager.config.LANGFUSE_PROPAGATION_SECRET.get_secret_value(), method, path, stamp, headers)
    return headers


def _metadata(baggage):
    for item in baggage.split(','):
        key, _, value = item.strip().partition('=')
        if key == 'hercfit-metadata':
            parsed = json.loads(unquote(value))
            return parsed if isinstance(parsed, dict) else {}
    return {}


def trusted_parent(config, method, path, headers):
    """Trả `{trace_id, parent_span_id, metadata}` khi header hợp lệ, có chữ ký và còn hạn 60 s."""
    secret = config.LANGFUSE_PROPAGATION_SECRET
    if not secret or not headers.get('traceparent'):
        return None
    if sum(len(headers.get(k, '')) for k in TRACE_HEADERS) > 8192:
        return None
    try:
        stamp = headers['x-hercfit-trace-time']
        if abs(time.time() - int(stamp)) > 60:
            return None
        expected = _signature(secret.get_secret_value(), method, path, stamp, headers)
        if not hmac.compare_digest(expected, headers.get('x-hercfit-trace-signature', '')):
            return None
        match = TRACEPARENT.match(headers['traceparent'])
        if not match:
            return None
        return {'trace_id': match[1], 'parent_span_id': match[2], 'metadata': _metadata(headers.get('baggage', ''))}
    except (KeyError, ValueError, TypeError):
        return None
