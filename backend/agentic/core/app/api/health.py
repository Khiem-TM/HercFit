from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agentic.observability import metrics, observer

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "hercfit-agentic"}


@router.get("/health/ready")
async def ready(request: Request):
    try:
        runtime = request.app.state.runtime
        await runtime.store.ready()
        response = await request.app.state.backend.http.get("/health/ready")
        response.raise_for_status()
        result = {"status": "ready", "observability": observer().status()}
        if runtime.memory is not None:
            # Redis chỉ được báo cáo; checkpoint vẫn phục vụ chat khi Redis lỗi.
            result["session_memory"] = await runtime.memory.health()
        return result
    except Exception:
        return JSONResponse({"status": "not_ready"}, status_code=503)


@router.get("/health/metrics", include_in_schema=False)
async def metrics_snapshot():
    """Số đo vận hành của tiến trình này (không nội dung, không định danh); chỉ mạng nội bộ, Caddy không proxy."""
    return {
        "service": "hercfit-agentic",
        "observability": observer().status(),
        **metrics.snapshot(),
    }
