"""Only signed service-to-service headers may continue a trace."""
import hashlib
import hmac
import json
import time
from urllib.parse import quote
from agentic.observability.tracing import current, durable_context

TRACE_HEADERS = {'langsmith-trace', 'baggage', 'x-hercfit-trace-time', 'x-hercfit-trace-signature'}


def _signature(secret, method, path, timestamp, headers):
    message = '\n'.join((method.upper(), path.split('?')[0], timestamp, headers.get('langsmith-trace', ''), headers.get('baggage', '')))
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def outbound_headers(method, path):
    state = current.get()
    if not state or not state.manager.config.LANGSMITH_PROPAGATION_SECRET:
        return {}
    context = durable_context()
    if not context:
        return {}
    headers = dict(context['headers'])
    stamp = str(int(time.time()))
    headers['x-hercfit-trace-time'] = stamp
    headers['x-hercfit-trace-signature'] = _signature(state.manager.config.LANGSMITH_PROPAGATION_SECRET.get_secret_value(), method, path, stamp, headers)
    return headers


def trusted_parent(config, method, path, headers):
    secret = config.LANGSMITH_PROPAGATION_SECRET
    if not secret or not headers.get('langsmith-trace'):
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
        return {k: headers[k] for k in ('langsmith-trace', 'baggage') if k in headers}
    except (KeyError, ValueError, TypeError):
        return None
