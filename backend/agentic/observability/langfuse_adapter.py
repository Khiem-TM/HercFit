"""Trace theo request xuất sang Langfuse: span lồng nhau, callback LangChain gốc và che dữ liệu trước khi xuất.

SDK Langfuse (OpenTelemetry) tự gom lô và xuất trên luồng nền có giới hạn; module này chỉ
quyết định cái gì được ghi. Mọi input/output/metadata đi qua `mask` (chạy đồng bộ trên luồng
gọi, nên đọc được request hiện tại); `metadata_only` còn xoá hẳn nội dung lúc xuất.
"""
import asyncio
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache, wraps
import inspect
import json
import logging
from time import monotonic
from urllib.parse import quote
from uuid import uuid4

from langfuse import Langfuse, LangfuseOtelSpanAttributes, propagate_attributes
from langfuse.types import MaskOtelSpansResult, OtelSpanPatch
from opentelemetry import trace as otel_trace

from agentic.observability.settings import ObservabilitySettings
from agentic.observability.privacy import bounded, pseudonym

log = logging.getLogger('hercfit.observability')
current = ContextVar('hercfit_observation', default=None)
META_KEYS = {'request_id', 'thread_id', 'business_run_id', 'graph_thread_id', 'action_id', 'linked_trace_id', 'environment', 'service', 'revision', 'operation', 'agent', 'model_role', 'hercfit_provider', 'hercfit_model', 'domain', 'intent', 'status', 'error_code', 'cost_status', 'usage_metadata', 'research', 'cache_hit', 'attempt', 'http_status', 'method', 'route', 'result_count', 'chunk_count', 'fact_count', 'projection_lag_ms', 'budget_exceeded', 'queue_wait_ms', 'job_id', 'event_id', 'retry_count', 'first_progress_ms', 'answer_ms', 'confirmation_wait_ms', 'decision', 'truncated', 'template_id', 'duration_ms', 'input_count', 'output_count', 'sampling_rate', 'phase', 'fallback', 'source_count', 'citation_count', 'sufficient', 'missing_count', 'conflict_count', 'node', 'model', 'tool', 'not_found', 'budget_kind', 'research_mode', 'research_web_calls', 'research_search_calls', 'research_llm_calls', 'research_rounds', 'citation_rejected_count'}
META_KEYS.update({'jev_mode', 'jev_phase', 'jev_status', 'jev_fallback', 'jev_model', 'jev_policy_version', 'jev_confidence', 'jev_cost', 'jev_input_tokens', 'jev_output_tokens', 'jev_attempted', 'jev_probabilities'})
META_KEYS.update({'memory_mode', 'memory_summary_chars', 'memory_entity_count', 'memory_gap_turns', 'memory_message_count', 'memory_checkpoint_count'})
# Khoá cấp request: được giữ lại và ghi lên span gốc khi request kết thúc.
STATE_KEYS = {'business_run_id', 'graph_thread_id', 'action_id', 'linked_trace_id', 'domain', 'intent',
              'research', 'first_progress_ms', 'answer_ms', 'confirmation_wait_ms', 'decision', 'budget_exceeded'}
# Kiểu span cũ (run_type) → kiểu observation của Langfuse.
OBSERVATION_TYPES = {'chain': 'chain', 'tool': 'tool', 'retriever': 'retriever', 'embedding': 'embedding',
                     'reranker': 'embedding', 'llm': 'generation', 'agent': 'agent'}
CONTENT_ATTRIBUTES = (LangfuseOtelSpanAttributes.OBSERVATION_INPUT, LangfuseOtelSpanAttributes.OBSERVATION_OUTPUT)
FAILED = {'failed', 'timeout'}
RESULT_STATUSES = {'completed', 'failed', 'needs_input', 'pending_confirmation'}


@dataclass
class Observation:
    manager: object
    request_id: str = field(default_factory=lambda: str(uuid4()))
    # 32 ký tự hex: định dạng trace ID của W3C/Langfuse.
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    metadata: dict = field(default_factory=dict)
    private_values: tuple = ()
    started: float = field(default_factory=monotonic)
    root: object = None
    sampled: bool = True
    user_id: str | None = None
    session_id: str | None = None
    otel_root: object = None
    outputs: object = None

    def identify(self, user_id, session_id=None, private_values=()):
        secret = self.manager.config.LANGFUSE_PSEUDONYM_SECRET
        if secret:
            secret = secret.get_secret_value()
            # Langfuse chỉ thấy bí danh HMAC; màn Users/Sessions vẫn gom đúng người/phiên.
            self.user_id = pseudonym(secret, user_id)
            if session_id:
                self.session_id = self.metadata['thread_id'] = pseudonym(secret, f'{user_id}:{session_id}')
            if self.otel_root is not None and self.otel_root.is_recording():
                self.otel_root.set_attribute(LangfuseOtelSpanAttributes.TRACE_USER_ID, self.user_id)
                if self.session_id:
                    self.otel_root.set_attribute(LangfuseOtelSpanAttributes.TRACE_SESSION_ID, self.session_id)
        self.private_values = tuple(dict.fromkeys((*self.private_values, str(user_id), str(session_id) if session_id else '', *(str(v) for v in private_values if v))))


class Run:
    """Tay cầm span cho nơi gọi: ghi metadata, lỗi và output, áp dụng một lần khi span đóng."""

    def __init__(self, observation):
        self.observation = observation
        self.metadata = {}
        self.error = None
        self.outputs = None

    def add_metadata(self, metadata):
        self.metadata.update({k: v for k, v in metadata.items() if k in META_KEYS})

    def end(self, outputs=None):
        self.outputs = outputs

    def apply(self):
        update = {'metadata': self.metadata} if self.metadata else {}
        if self.outputs is not None:
            update['output'] = self.outputs
        if self.error or self.metadata.get('status') in FAILED:
            update.update(level='ERROR', status_message=str(self.error or self.metadata.get('error_code') or 'OperationFailed'))
        elif self.metadata.get('status') == 'cancelled':
            update.update(level='WARNING', status_message='cancelled')
        if update:
            self.observation.update(**update)


class _ExportErrors(logging.Handler):
    """Đếm lỗi của logger `langfuse` để /health/ready báo được; không giữ nội dung thông điệp."""

    def __init__(self, owner):
        super().__init__(logging.ERROR)
        self.owner = owner

    def emit(self, record):
        self.owner.export_errors += 1
        self.owner.last_error = record.levelname + ':' + record.module


class Observer:
    def __init__(self, config=None, **client_options):
        self.config = config or ObservabilitySettings()
        self.client = None
        self.closed = False
        self.export_errors = 0
        self.last_error = None
        if self.config.enabled and self.config.configured:
            try:
                metadata_only = self.config.LANGFUSE_CAPTURE_MODE == 'metadata_only'
                self.client = Langfuse(
                    public_key=self.config.LANGFUSE_PUBLIC_KEY, secret_key=self.config.LANGFUSE_SECRET_KEY.get_secret_value(),
                    base_url=self.config.LANGFUSE_BASE_URL, environment=self.config.LANGFUSE_TRACING_ENVIRONMENT,
                    release=self.config.LANGFUSE_RELEASE, timeout=5, tracing_enabled=True,
                    # Lấy mẫu do HercFit quyết định theo trace ID để cả cây cùng vào hoặc cùng ra.
                    sample_rate=1.0, mask=self.mask, mask_otel_spans=drop_content if metadata_only else None,
                    **client_options)
                logging.getLogger('langfuse').addHandler(_ExportErrors(self))
            except Exception as exc:
                self.client = None
                self.export_error(exc)
        elif self.config.enabled:
            log.warning('tracing_disabled reason=missing_langfuse_keys')

    def export_error(self, exc):
        code = type(exc).__name__
        if self.last_error != code:
            log.warning('trace_export_failed error_type=%s', code)
        self.last_error = code

    def mask(self, *, data, **_):
        state = current.get()
        secret = self.config.LANGFUSE_PSEUDONYM_SECRET.get_secret_value() if self.config.LANGFUSE_PSEUDONYM_SECRET else ''
        return bounded(data, private_values=state.private_values if state else (), secret=secret)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.client:
            try:
                await asyncio.wait_for(asyncio.to_thread(self.client.shutdown), self.config.LANGFUSE_FLUSH_SECONDS)
            except Exception as exc:
                self.export_error(exc)

    def status(self):
        return {'enabled': bool(self.client), 'configured': self.config.configured,
                'propagation_configured': bool(self.config.LANGFUSE_PROPAGATION_SECRET),
                'capture_mode': self.config.LANGFUSE_CAPTURE_MODE,
                'export_errors': self.export_errors, 'last_export_error': self.last_error}

    @contextmanager
    def request(self, name, service, *, parent=None, state=None):
        state = state or Observation(self)
        if parent:
            state.trace_id = parent['trace_id']
            state.metadata.update({k: v for k, v in (parent.get('metadata') or {}).items() if k in {'thread_id', 'business_run_id', 'action_id'}})
        # Lấy mẫu cả cây theo trace ID: backend tiếp tục trace của agent cho cùng quyết định.
        state.sampled = int(state.trace_id, 16) / 2**128 < self.config.LANGFUSE_SAMPLE_RATE
        state.metadata.update(service=service, operation=name, environment=self.config.LANGFUSE_TRACING_ENVIRONMENT,
                              revision=self.config.LANGFUSE_RELEASE, request_id=state.request_id,
                              sampling_rate=self.config.LANGFUSE_SAMPLE_RATE)
        mark = current.set(state)
        try:
            if not (self.client and state.sampled and not self.closed):
                yield state
                return
            trace_context = {'trace_id': state.trace_id}
            if parent and parent.get('parent_span_id'):
                trace_context['parent_span_id'] = parent['parent_span_id']
            tags = [f'env:{self.config.LANGFUSE_TRACING_ENVIRONMENT}', f'service:{service}']
            with ExitStack() as stack:
                stack.enter_context(propagate_attributes(tags=tags, metadata={'request_id': state.request_id}))
                root = stack.enter_context(self.client.start_as_current_observation(
                    name=name, as_type='span', trace_context=trace_context, metadata=_meta(state.metadata)))
                state.root, state.otel_root = root, otel_trace.get_current_span()
                run = Run(root)
                try:
                    yield state
                except BaseException as exc:
                    state.metadata.update(status='cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed', error_code=type(exc).__name__)
                    raise
                finally:
                    for tag in ('research', 'budget_exceeded'):
                        if state.metadata.get(tag):
                            state.otel_root.set_attribute(LangfuseOtelSpanAttributes.TRACE_TAGS, [*tags, tag])
                    run.metadata, run.outputs = _meta(state.metadata), state.outputs
                    run.apply()
        finally:
            current.reset(mark)


def _meta(metadata):
    return {k: v for k, v in metadata.items() if k in META_KEYS and v is not None}


def drop_content(*, params):
    """`metadata_only`: xoá input/output khỏi mọi span ngay trước khi xuất, giữ thời gian/trạng thái/usage."""
    patches = {}
    for identifier, span in params.spans.items():
        keys = tuple(k for k in CONTENT_ATTRIBUTES if k in span.attributes)
        if keys:
            patches[identifier] = OtelSpanPatch(delete_attributes=keys)
    return MaskOtelSpansResult(span_patches=patches)


@lru_cache
def observer():
    return Observer()


def identify(user_id, session_id=None, private_values=()):
    if state := current.get():
        state.identify(user_id, session_id, private_values)


def _live(state):
    return bool(state and state.manager.client and state.sampled and not state.manager.closed)


def annotate(**metadata):
    state = current.get()
    if state:
        state.metadata.update({k: v for k, v in metadata.items() if k in STATE_KEYS})
    if _live(state):
        values = _meta(metadata)
        if values:
            try:
                state.manager.client.update_current_span(metadata=values)
            except Exception as exc:
                state.manager.export_error(exc)


def outcome(status, **metadata):
    if state := current.get():
        state.metadata.update(status=status, **{k: v for k, v in metadata.items() if k in META_KEYS})
    annotate(status=status, **metadata)


@contextmanager
def span(name, run_type='chain', *, inputs=None, **metadata):
    state = current.get()
    if not _live(state):
        yield None
        return
    with ExitStack() as stack:
        if state.user_id:
            # Span con mang user/session để lọc được theo người dùng ở mọi cấp.
            stack.enter_context(propagate_attributes(user_id=state.user_id, session_id=state.session_id))
        observation = stack.enter_context(state.manager.client.start_as_current_observation(
            name=name, as_type=OBSERVATION_TYPES.get(run_type, 'span'), input=inputs or None, metadata=_meta(metadata) or None))
        run = Run(observation)
        try:
            yield run
            run.metadata.setdefault('status', 'completed')
        except BaseException as exc:
            run.metadata.update(error_code=type(exc).__name__, status='cancelled' if isinstance(exc, asyncio.CancelledError) else 'failed')
            raise
        finally:
            run.apply()


def _result_value(result):
    value = result.model_dump(mode='json') if hasattr(result, 'model_dump') else result
    return value if isinstance(value, dict) else {'result': value}


def observed(name, run_type='chain', *, capture=(), output=True):
    def decorate(fn):
        signature = inspect.signature(fn)

        @wraps(fn)
        async def wrapped(*args, **kwargs):
            inputs = {}
            if capture:
                bound = signature.bind(*args, **kwargs).arguments
                inputs = {k: bound[k] for k in capture if k in bound}
            if current.get() is None:
                with observer().request(name, 'worker' if 'worker' in name else 'agentic') as state:
                    result = await fn(*args, **kwargs)
                    if output:
                        state.outputs = _result_value(result)
                    state.metadata.setdefault('status', 'completed')
                    return result
            with span(name, run_type, inputs=inputs) as run:
                result = await fn(*args, **kwargs)
                if run and output:
                    value = _result_value(result)
                    run.end(outputs=value)
                    if value.get('status') in RESULT_STATUSES:
                        run.add_metadata({'status': value['status']})
                        state = current.get()
                        if name in {'runtime.chat', 'runtime.confirm'} and state and state.metadata.get('status') not in {'timeout', 'rejected'}:
                            outcome(value['status'])
                return result
        return wrapped
    return decorate


def graph_config(config=None):
    """Gắn đúng một CallbackHandler Langfuse; span LangChain/LangGraph lồng dưới observation hiện tại."""
    config = dict(config or {})
    state = current.get()
    if not _live(state):
        return config
    from langfuse.langchain import CallbackHandler
    callbacks = config.get('callbacks')
    if callbacks is None:
        config['callbacks'] = [CallbackHandler(public_key=state.manager.config.LANGFUSE_PUBLIC_KEY)]
    elif isinstance(callbacks, list):
        config['callbacks'] = [*callbacks] if any(isinstance(c, CallbackHandler) for c in callbacks) else [*callbacks, CallbackHandler(public_key=state.manager.config.LANGFUSE_PUBLIC_KEY)]
    else:
        config['callbacks'] = callbacks.copy()
        if not any(isinstance(c, CallbackHandler) for c in callbacks.handlers):
            config['callbacks'].add_handler(CallbackHandler(public_key=state.manager.config.LANGFUSE_PUBLIC_KEY), inherit=True)
    metadata = {**config.get('metadata', {}), **_meta(state.metadata)}
    # `configurable.thread_id` của graph KHÔNG phải luồng hội thoại; giữ bí danh hội thoại.
    if state.user_id:
        metadata['langfuse_user_id'] = state.user_id
    if state.session_id:
        metadata['langfuse_session_id'] = state.session_id
    config['metadata'] = metadata
    return config


def durable_context():
    """Ngữ cảnh mờ lưu vào DB/hàng đợi để worker và backend nối lại đúng trace."""
    state = current.get()
    if not _live(state):
        return None
    observation_id = state.manager.client.get_current_observation_id()
    if not observation_id:
        return None
    metadata = {k: v for k, v in state.metadata.items() if k in {'thread_id', 'business_run_id', 'action_id', 'environment'}}
    headers = {'traceparent': f'00-{state.trace_id}-{observation_id}-01',
               'baggage': 'hercfit-metadata=' + quote(json.dumps(metadata))}
    return {'trace_id': state.trace_id, 'headers': headers, 'metadata': metadata}
