"""Transaction management decorator for FastAPI endpoint handlers."""

from functools import wraps
from typing import Any, Callable
from core.idempotency import active_request, execute_idempotent


def transaction(func: Callable[..., Any]) -> Callable[..., Any]:

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        session = kwargs.get("session")
        if session is None:
            for val in kwargs.values():
                if hasattr(val, "session"):
                    session = getattr(val, "session")
                    break

        if session is not None and getattr(session, "is_active", False):
            try:
                request = active_request.get()
                service = kwargs.get("service")
                if request is not None and service is not None:
                    result = await execute_idempotent(
                        request, service, lambda: func(*args, **kwargs), kwargs.get("response")
                    )
                else:
                    result = await func(*args, **kwargs)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise

        return await func(*args, **kwargs)

    return wrapper

