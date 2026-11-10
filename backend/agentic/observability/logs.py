"""Cấu hình logging dùng chung cho API agentic, backend và worker.

Trước đây không tiến trình nào áp dụng LOG_LEVEL: logger gốc giữ mặc định WARNING của Python nên log INFO
`request_finished` (tương quan request_id ↔ trace_id) không bao giờ được ghi. Hàm này idempotent và không
đụng tới logger của uvicorn.
"""

import logging

REQUEST_LOGGERS = ("hercfit.requests", "hercfit.chat")
FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _level(value, default):
    if isinstance(value, int):
        return value
    resolved = logging.getLevelName(str(value or "").upper())
    return resolved if isinstance(resolved, int) else default


def configure_logging(level="WARNING", request_level="INFO", *, model_retries=False):
    root = logging.getLogger()
    if not any(getattr(handler, "_hercfit", False) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(FORMAT))
        handler._hercfit = True
        root.addHandler(handler)
    root.setLevel(_level(level, logging.WARNING))
    for name in REQUEST_LOGGERS:
        logging.getLogger(name).setLevel(_level(request_level, logging.INFO))
    if model_retries:
        # Chỉ tiến trình gọi model (agentic) cần đếm retry nội bộ của SDK OpenAI.
        from agentic.observability.telemetry import install_sdk_retry_counter

        install_sdk_retry_counter()
    return root


def configure_from_settings(config=None, *, model_retries=False):
    from agentic.observability.settings import ObservabilitySettings

    config = config or ObservabilitySettings()
    return configure_logging(
        config.LOG_LEVEL, config.REQUEST_LOG_LEVEL, model_retries=model_retries
    )
