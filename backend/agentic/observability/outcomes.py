"""Kết cục cấp ứng dụng của một phiên chat, độc lập với mã HTTP.

SSE trả 200 ngay khi stream mở, nên lỗi xảy ra sau đó (model lỗi, hết giờ, client rời đi) không bao giờ thấy được
qua `http_status`. Mỗi phiên chat (`/chat`, `/chat/stream`, `/chat/confirm`) có đúng một kết cục cuối:

    chat_started → [chat_first_token] → chat_completed | chat_failed | chat_timeout | chat_cancelled

Kết cục được ghi một lần vào log `hercfit.chat`, số đo tiến trình (`metrics`) và span gốc Langfuse. Lỗi sâu
trong graph (node, model, backend) được ghi chú qua `note_error` để phân loại lớp lỗi: `provider` (nhà cung cấp
model), `timeout` (hết ngân sách thời gian), `server` (mã của HercFit, backend, checkpoint), `client` (yêu cầu bị
từ chối 4xx) và `client_disconnect` (client đóng kết nối). Không ghi nội dung tin nhắn hay định danh người dùng.
"""

import logging
from contextvars import ContextVar
from time import monotonic

from agentic.observability import metrics

log = logging.getLogger("hercfit.chat")
active = ContextVar("hercfit_chat_session", default=None)

COMPLETED, FAILED, TIMEOUT, CANCELLED = "completed", "failed", "timeout", "cancelled"
EVENTS = {
    COMPLETED: "chat_completed",
    FAILED: "chat_failed",
    TIMEOUT: "chat_timeout",
    CANCELLED: "chat_cancelled",
}
PROVIDER, SERVER, CLIENT, DISCONNECT = "provider", "server", "client", "client_disconnect"
# Lớp lỗi của SDK OpenAI/LangChain: lỗi tại nhà cung cấp model, không phải mã của HercFit.
PROVIDER_ERRORS = {
    "APIError",
    "APIStatusError",
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "InternalServerError",
    "AuthenticationError",
    "OpenAIAuthenticationError",
    "PermissionDeniedError",
    "BadRequestError",
    "UnprocessableEntityError",
    "ConflictError",
    "NotFoundError",
}
TIMEOUT_ERRORS = {"TimeoutError", "CancelledByTimeout"}
RESULT_OUTCOMES = {
    "completed": COMPLETED,
    "needs_input": COMPLETED,
    "pending_confirmation": COMPLETED,
}


def classify(error):
    """Lớp lỗi từ exception hoặc tên lớp của nó."""
    if isinstance(error, BaseException):
        module = type(error).__module__ or ""
        name = type(error).__name__
        if module.startswith(("openai", "langchain_openai")):
            return PROVIDER
    else:
        name = str(error)
    if name in TIMEOUT_ERRORS:
        return TIMEOUT
    if name in PROVIDER_ERRORS:
        return PROVIDER
    return SERVER


def provider_kind(error):
    """Loại lỗi nhà cung cấp cho số đo lần gọi model: rate_limit, timeout, connection, server, auth, other."""
    name = error if isinstance(error, str) else type(error).__name__
    return {
        "RateLimitError": "rate_limit",
        "APITimeoutError": "timeout",
        "TimeoutError": "timeout",
        "APIConnectionError": "connection",
        "InternalServerError": "server",
        "AuthenticationError": "auth",
        "OpenAIAuthenticationError": "auth",
        "PermissionDeniedError": "auth",
    }.get(name, "other")


def note_error(error):
    """Ghi chú một lỗi vào phiên chat đang chạy (nếu có) để kết cục cuối phân loại đúng."""
    session = active.get()
    if session is not None:
        session.errors.append(
            (classify(error), error if isinstance(error, str) else type(error).__name__)
        )


class ChatSession:
    """Theo dõi một phiên chat; `finish` chỉ có hiệu lực lần đầu."""

    def __init__(self, endpoint, chat_mode="normal"):
        self.endpoint = endpoint
        self.chat_mode = chat_mode
        self.started = monotonic()
        self.first_token_ms = None
        self.outcome = None
        self.failure_class = None
        self.errors = []
        self._token = None

    def __enter__(self):
        self._token = active.set(self)
        metrics.incr("chat_started_total", endpoint=self.endpoint, chat_mode=self.chat_mode)
        log.info("chat_started endpoint=%s chat_mode=%s", self.endpoint, self.chat_mode)
        return self

    def __exit__(self, kind, error, _traceback):
        if self.outcome is None:
            if error is None:
                self.finish(COMPLETED)
            elif isinstance(error, (GeneratorExit,)) or kind.__name__ == "CancelledError":
                self.finish(CANCELLED, failure_class=DISCONNECT)
            else:
                self.finish(FAILED, error=error)
        if self._token is not None:
            try:
                active.reset(self._token)
            except ValueError:
                # Async generator bị đóng từ ngữ cảnh khác (client rời đi): biến ngữ cảnh tự hết hạn cùng task.
                pass
            self._token = None
        return False

    def elapsed_ms(self):
        return round((monotonic() - self.started) * 1000, 3)

    def first_token(self):
        if self.first_token_ms is not None or self.outcome is not None:
            return
        self.first_token_ms = self.elapsed_ms()
        metrics.observe(
            "chat_ttft_ms", self.first_token_ms, endpoint=self.endpoint, chat_mode=self.chat_mode
        )
        log.info(
            "chat_first_token endpoint=%s first_token_ms=%.3f", self.endpoint, self.first_token_ms
        )
        _annotate(first_token_ms=self.first_token_ms)

    def finish_result(self, status):
        """Kết cục từ trạng thái ChatResponse của runtime."""
        if status in RESULT_OUTCOMES:
            return self.finish(COMPLETED, result_status=status)
        classes = [cls for cls, _ in self.errors]
        if TIMEOUT in classes:
            return self.finish(TIMEOUT, failure_class=TIMEOUT, result_status=status)
        return self.finish(
            FAILED,
            failure_class=PROVIDER if PROVIDER in classes else SERVER,
            result_status=status,
        )

    def finish(
        self, outcome, *, failure_class=None, error=None, result_status=None, status_code=None
    ):
        if self.outcome is not None:
            return False
        if error is not None:
            failure_class = failure_class or classify(error)
            if failure_class == TIMEOUT:
                outcome = TIMEOUT
        if status_code is not None and failure_class is None:
            failure_class = CLIENT if 400 <= status_code < 500 else SERVER
        if outcome == FAILED and failure_class is None:
            failure_class = SERVER
        self.outcome, self.failure_class = outcome, failure_class
        duration = self.elapsed_ms()
        if isinstance(error, BaseException):
            error_code = type(error).__name__
        elif status_code is not None:
            error_code = f"HTTP{status_code}"
        else:
            error_code = self.errors[-1][1] if self.errors and outcome != COMPLETED else None
        metrics.incr(
            "chat_sessions_total",
            endpoint=self.endpoint,
            chat_mode=self.chat_mode,
            outcome=outcome,
            failure_class=failure_class or "none",
            result_status=result_status or "none",
        )
        metrics.observe("chat_duration_ms", duration, endpoint=self.endpoint, outcome=outcome)
        level = logging.INFO if outcome == COMPLETED else logging.WARNING
        log.log(
            level,
            "%s endpoint=%s chat_mode=%s failure_class=%s result_status=%s status_code=%s error_code=%s"
            " duration_ms=%.3f first_token_ms=%s",
            EVENTS[outcome],
            self.endpoint,
            self.chat_mode,
            failure_class,
            result_status,
            status_code,
            error_code,
            duration,
            self.first_token_ms,
        )
        _annotate(
            chat_outcome=outcome,
            failure_class=failure_class,
            chat_duration_ms=duration,
            chat_mode=self.chat_mode,
        )
        if outcome != COMPLETED:
            # Trạng thái của root trace theo kết cục ứng dụng, không theo HTTP 200 của stream.
            from agentic.observability import outcome as trace_outcome

            trace_outcome(
                {FAILED: "failed", TIMEOUT: "timeout", CANCELLED: "cancelled"}[outcome],
                error_code=error_code or failure_class,
            )
        return True


def _annotate(**values):
    try:
        from agentic.observability import annotate

        annotate(**{k: v for k, v in values.items() if v is not None})
    except Exception:  # noqa: BLE001 - telemetry không được làm hỏng phiên chat
        pass
