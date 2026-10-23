from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from agentic.clients.backend_client import BackendError
from agentic.core.context import RequestContext, request_context

bearer=HTTPBearer(auto_error=False)

# Xác thực User thông qua Bearer JWT
async def authenticated(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401,'Bearer JWT required')
    try:
        user=await request.app.state.backend.identity(credentials.credentials)
    except BackendError as exc:
        raise HTTPException(exc.status if exc.status in {401,403} else 503,'Authentication could not be verified') from None
    context=RequestContext(str(user.id),credentials.credentials,request.app.state.backend,(user.fullname, str(user.email)))
    mark=request_context.set(context)
    try:
        yield context
    finally:
        request_context.reset(mark)
