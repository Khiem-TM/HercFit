from hashlib import sha256
from time import monotonic
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from agentic.tools.integrations.backend_client import BackendError
from agentic.core.context import RequestContext, request_context

from observability import identify

bearer=HTTPBearer(auto_error=False)
# Verified identities, keyed by a token digest (never the token itself).
_identity_cache: dict[str, tuple[float, object]] = {}
_CACHE_MAX = 5000


async def _verified_user(request: Request, token: str):
    ttl = getattr(getattr(request.app.state, 'runtime', None) and request.app.state.runtime.settings,
                  'IDENTITY_CACHE_SECONDS', 0) or 0
    key = sha256(token.encode()).hexdigest()
    now = monotonic()
    hit = _identity_cache.get(key)
    if ttl and hit and hit[0] > now:
        return hit[1]
    user = await request.app.state.backend.identity(token)
    if ttl:
        if len(_identity_cache) >= _CACHE_MAX:
            for stale in [k for k, (expires, _u) in _identity_cache.items() if expires <= now] or list(_identity_cache)[:_CACHE_MAX // 2]:
                _identity_cache.pop(stale, None)
        _identity_cache[key] = (now + ttl, user)
    return user


# Xác thực User thông qua Bearer JWT
async def authenticated(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401,'Bearer JWT required')
    try:
        user=await _verified_user(request, credentials.credentials)
    except BackendError as exc:
        raise HTTPException(exc.status if exc.status in {401,403} else 503,'Authentication could not be verified') from None
    identify(str(user.id), private_values=(user.fullname, str(user.email), user.nick_name))
    context=RequestContext(str(user.id),credentials.credentials,request.app.state.backend,(user.fullname, str(user.email)))
    mark=request_context.set(context)
    try:
        yield context
    finally:
        request_context.reset(mark)
